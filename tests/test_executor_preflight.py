from pathlib import Path

import pytest

import multimodal_studio.executor as executor_module
from multimodal_studio.budget import RenderBudget, RenderBudgetExceeded
from multimodal_studio.executor import FFmpegExecutor, MediaProbe, _parse_frame_rate
from multimodal_studio.planner import EditNode


def test_frame_rate_parser_supports_ffprobe_rationals() -> None:
    assert _parse_frame_rate("30000/1001") == pytest.approx(29.97002997)
    assert _parse_frame_rate("24") == 24.0
    assert _parse_frame_rate("0/0") is None


def test_executor_preflight_enforces_render_budget(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "input.mp4"
    source.write_bytes(b"fake")

    monkeypatch.setattr(
        executor_module,
        "probe_media",
        lambda *args, **kwargs: MediaProbe(
            duration_seconds=600.0,
            width=3840,
            height=2160,
            fps=60.0,
            video_codec="h264",
            audio_codec="aac",
        ),
    )

    executor = FFmpegExecutor(
        render_budget=RenderBudget(max_operations=8, max_megapixel_frames=1_000)
    )
    with pytest.raises(RenderBudgetExceeded, match="megapixel-frames"):
        executor._preflight(
            source,
            [EditNode("color_grade", {"preset": "cinematic-teal"}, "color")],
        )
