"""End-to-end makma.v1 checks against real FFmpeg/FFprobe binaries.

These tests are skipped when ffmpeg/ffprobe are not on PATH. The fixture is a
synthetic one-second lavfi test pattern generated at test time.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from multimodal_studio.contracts import WORKSPACE_ENV, run_operation

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="real FFmpeg/FFprobe binaries required",
)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv(WORKSPACE_ENV, str(tmp_path))
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=64x64:rate=12",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=8000",
            "-t", "1", "-c:v", "mpeg4", "-c:a", "aac", "-shortest",
            str(tmp_path / "input.mp4"),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return tmp_path


def test_execute_renders_and_verifies_a_real_artifact(workspace: Path) -> None:
    env = run_operation(
        "execute",
        {
            "source_path": "input.mp4",
            "destination_path": "output.mp4",
            "approved": True,
            "timeout_seconds": 60,
            "nodes": [
                {"operation": "resize", "stage": "vision",
                 "parameters": {"width": 48, "height": 48}},
                {"operation": "trim", "stage": "temporal",
                 "parameters": {"start_seconds": 0, "end_seconds": 0.5}},
            ],
        },
    )
    assert env["status"] == "ok", env["error"]
    artifact = env["data"]["artifact"]
    assert artifact["probe_status"] == "verified"
    assert artifact["passed"]
    assert (artifact["media"]["width"], artifact["media"]["height"]) == (48, 48)

    verified = run_operation(
        "verify_artifact",
        {
            "path": "output.mp4",
            "expected_sha256": artifact["sha256"],
            "expected_width": 48,
            "expected_height": 48,
            "expected_duration_seconds": 0.5,
            "duration_tolerance_seconds": 0.25,
            "require_video": True,
        },
    )
    assert verified["status"] == "ok"
    assert verified["data"]["passed"], verified["data"]["problems"]


def test_verify_artifact_reports_probe_failure_for_non_media(workspace: Path) -> None:
    (workspace / "not-media.mp4").write_bytes(b"this is not a media file")
    env = run_operation("verify_artifact", {"path": "not-media.mp4", "require_video": True})
    assert env["status"] == "ok"
    assert env["data"]["probe_status"] == "failed"
    assert env["data"]["passed"] is False
