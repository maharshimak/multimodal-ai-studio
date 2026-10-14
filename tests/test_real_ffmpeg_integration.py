"""Small real-media checks; generated fixtures contain no user media or provider calls."""
import shutil
import subprocess

import pytest

from multimodal_studio.executor import FFmpegExecutor, MediaExecutionError, probe_media
from multimodal_studio.planner import EditNode

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="real FFmpeg/FFprobe binaries required",
)


@pytest.fixture
def tiny_video(tmp_path):
    source = tmp_path / "input.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=12",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=8000",
            "-t", "1", "-c:v", "mpeg4", "-c:a", "aac",
            "-shortest", str(source),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert source.stat().st_size > 0
    return source


def test_real_ffmpeg_can_atomically_replace_existing_media(tmp_path, tiny_video):
    output = tmp_path / "published.mp4"
    output.write_bytes(b"previous-version")
    executor = FFmpegExecutor(timeout_seconds=60)
    result = executor.execute(
        tiny_video, output,
        [EditNode("resize", {"width": 48, "height": 48}, "vision")],
    )
    assert result == output
    assert result.read_bytes() != b"previous-version"
    metadata = probe_media(result)
    assert (metadata.width, metadata.height) == (48, 48)
    assert metadata.duration_seconds is not None
    assert metadata.duration_seconds > 0
    assert list(tmp_path.glob(".render-*")) == []


def test_real_ffmpeg_invalid_crop_keeps_previous_publish(tmp_path, tiny_video):
    target = tmp_path / "published.mp4"
    target.write_bytes(b"preserve-existing")
    executor = FFmpegExecutor(timeout_seconds=60)
    with pytest.raises(MediaExecutionError, match="FFmpeg failed"):
        executor.execute(
            tiny_video, target,
            [EditNode(
                "crop", {"width": 512, "height": 512, "x": 0, "y": 0}, "vision",
            )],
        )
    assert target.read_bytes() == b"preserve-existing"
    assert list(tmp_path.glob(".render-*")) == []
