from pathlib import Path

import pytest

import multimodal_studio.executor as executor_module
from multimodal_studio.budget import (
    MediaProfile,
    RenderBudget,
    RenderBudgetExceeded,
    enforce_output_budget,
)
from multimodal_studio.executor import FFmpegExecutor, FFmpegUnavailableError, MediaProbe
from multimodal_studio.planner import EditNode
from multimodal_studio.timeline import MediaPlanError

HD = MediaProfile(width=1920, height=1080, duration_seconds=120.0, fps=25.0)


def test_output_budget_limits_projected_duration() -> None:
    slow = [EditNode("retime", {"speed": 0.5}, "temporal")]
    with pytest.raises(RenderBudgetExceeded, match="output duration"):
        enforce_output_budget(slow, HD, RenderBudget(max_output_seconds=200))
    assert enforce_output_budget(slow, HD, RenderBudget(max_output_seconds=240)).duration_seconds == 240


def test_output_budget_limits_projected_resolution() -> None:
    upscale = [EditNode("resize", {"width": 3840, "height": 2160}, "vision")]
    with pytest.raises(RenderBudgetExceeded, match="output resolution"):
        enforce_output_budget(upscale, HD, RenderBudget(max_output_pixels=1920 * 1080))


@pytest.mark.parametrize("field", ["max_output_seconds", "max_output_pixels"])
@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True])
def test_output_budget_fields_are_validated(field, value) -> None:
    with pytest.raises((TypeError, ValueError)):
        RenderBudget(**{field: value})


def _fake_probe(monkeypatch, **overrides) -> None:
    values = {
        "duration_seconds": 30.0, "width": 1280, "height": 720, "fps": 25.0,
        "video_codec": "h264", "audio_codec": "aac",
    }
    values.update(overrides)
    monkeypatch.setattr(executor_module, "probe_media", lambda *a, **k: MediaProbe(**values))


def test_preflight_rejects_trim_past_source_end(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "in.mp4"
    source.write_bytes(b"synthetic")
    _fake_probe(monkeypatch)
    with pytest.raises(MediaPlanError, match="Trim start"):
        FFmpegExecutor()._preflight(
            source, [EditNode("trim", {"start_seconds": 45, "end_seconds": 50}, "temporal")]
        )


def test_preflight_rejects_crop_outside_source(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "in.mp4"
    source.write_bytes(b"synthetic")
    _fake_probe(monkeypatch)
    with pytest.raises(MediaPlanError, match="Crop window"):
        FFmpegExecutor()._preflight(
            source, [EditNode("crop", {"width": 1080, "height": 1080, "x": 0, "y": 0}, "vision")]
        )


def test_preflight_accepts_compatible_plan(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "in.mp4"
    source.write_bytes(b"synthetic")
    _fake_probe(monkeypatch)
    probe = FFmpegExecutor()._preflight(
        source, [EditNode("trim", {"start_seconds": 5, "end_seconds": 50}, "temporal")]
    )
    assert probe.width == 1280


def test_missing_ffprobe_raises_typed_unavailable_error(tmp_path: Path) -> None:
    source = tmp_path / "in.mp4"
    source.write_bytes(b"synthetic")
    with pytest.raises(FFmpegUnavailableError) as raised:
        executor_module.probe_media(source, ffprobe_binary="definitely-not-ffprobe-binary")
    assert raised.value.binary == "definitely-not-ffprobe-binary"
