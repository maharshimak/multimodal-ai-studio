from multimodal_studio.executor import build_ffmpeg_command
from multimodal_studio.planner import EditNode


def test_typed_edit_graph_builds_real_ffmpeg_filters() -> None:
    command = build_ffmpeg_command(
        "input.mp4",
        "output.mp4",
        [
            EditNode("crop", {"width": 1080, "height": 1080, "x": 100, "y": 0}, "vision"),
            EditNode("resize", {"width": 720, "height": 720}, "vision"),
            EditNode("trim", {"start_seconds": 2, "end_seconds": 8}, "temporal"),
            EditNode("volume", {"gain_db": -3}, "audio"),
        ],
    )

    video = command[command.index("-vf") + 1]
    audio = command[command.index("-af") + 1]
    assert "crop=1080:1080:100:0" in video
    assert "scale=720:720:flags=lanczos" in video
    assert "trim=start=2:end=8" in video
    assert "volume=-3dB" in audio
