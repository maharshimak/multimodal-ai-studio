"""End-to-end makma.v1 checks against real FFmpeg/FFprobe binaries.

Skipped when ffmpeg/ffprobe are not on PATH, unless ``MAKMA_REQUIRE_FFMPEG=1``
is set (as in ``.github/workflows/real-media.yml``), in which case missing
binaries are a test failure. Sources are synthetic lavfi test patterns
generated at test time.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from multimodal_studio.contracts import WORKSPACE_ENV, run_operation

REQUIRE_FFMPEG = os.environ.get("MAKMA_REQUIRE_FFMPEG") == "1"
HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

pytestmark = pytest.mark.skipif(
    not HAVE_FFMPEG and not REQUIRE_FFMPEG,
    reason="real FFmpeg/FFprobe binaries required (set MAKMA_REQUIRE_FFMPEG=1 to fail instead)",
)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    if not HAVE_FFMPEG:
        pytest.fail("MAKMA_REQUIRE_FFMPEG=1 but ffmpeg/ffprobe are not on PATH")
    monkeypatch.setenv(WORKSPACE_ENV, str(tmp_path))
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=64x64:rate=12",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=8000",
            "-t", "3", "-c:v", "mpeg4", "-c:a", "aac", "-shortest",
            str(tmp_path / "input.mp4"),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return tmp_path


def test_execute_renders_an_artifact_that_passes_probe_validation(workspace: Path) -> None:
    env = run_operation(
        "execute",
        {
            "source_path": "input.mp4",
            "destination_path": "output.mp4",
            "approved": True,
            "timeout_seconds": 120,
            "nodes": [
                {"operation": "resize", "stage": "vision",
                 "parameters": {"width": 48, "height": 32}},
                {"operation": "trim", "stage": "temporal",
                 "parameters": {"start_seconds": 0.5, "end_seconds": 2.5}},
                {"operation": "volume", "stage": "audio", "parameters": {"gain_db": -3}},
            ],
        },
    )
    assert env["status"] == "ok", env["error"]
    projected = env["data"]["projected_output"]
    assert (projected["width"], projected["height"]) == (48, 32)
    assert projected["duration_seconds"] == pytest.approx(2.0)
    artifact = env["data"]["artifact"]
    assert artifact["probe_status"] == "verified"
    assert artifact["passed"], artifact["problems"]
    output = workspace / "output.mp4"
    assert output.is_file() and output.stat().st_size > 0

    verified = run_operation(
        "verify_artifact",
        {
            "path": "output.mp4",
            "expected_sha256": artifact["sha256"],
            "expected_width": projected["width"],
            "expected_height": projected["height"],
            "expected_duration_seconds": projected["duration_seconds"],
            "duration_tolerance_seconds": 0.25,
            "require_video": True,
            "require_audio": True,
        },
    )
    assert verified["status"] == "ok", verified["error"]
    data = verified["data"]
    assert data["probe_status"] == "verified"
    assert data["checks"] == {
        "non_empty": True,
        "sha256": True,
        "width": True,
        "height": True,
        "duration": True,
        "has_video": True,
        "has_audio": True,
    }, data["problems"]
    assert data["passed"] is True


def test_execute_unsupported_operation_fails_clearly_without_output(workspace: Path) -> None:
    env = run_operation(
        "execute",
        {
            "source_path": "input.mp4",
            "destination_path": "subtitled.mp4",
            "approved": True,
            "prompt": "add subtitles and replace background",
        },
    )
    assert env["status"] == "error"
    assert env["data"] is None
    assert env["error"]["code"] == "UNSUPPORTED_OPERATION"
    assert env["error"]["details"]["operations"] == ["background_segmentation", "subtitles"]
    assert not (workspace / "subtitled.mp4").exists()


def test_verify_artifact_reports_probe_failure_for_non_media(workspace: Path) -> None:
    (workspace / "not-media.mp4").write_bytes(b"this is not a media file")
    env = run_operation("verify_artifact", {"path": "not-media.mp4", "require_video": True})
    assert env["status"] == "ok"
    assert env["data"]["probe_status"] == "failed"
    assert env["data"]["passed"] is False
