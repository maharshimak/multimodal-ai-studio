from pathlib import Path

import pytest

from multimodal_studio.executor import MediaExecutionError, build_ffmpeg_command
from multimodal_studio.planner import EditNode, plan


def test_build_ffmpeg_command_executes_supported_plan_without_shell() -> None:
    command = build_ffmpeg_command(
        "input.mp4",
        "output.mp4",
        plan("cinematic teal, slow motion, remove background noise"),
    )

    assert command[0] == "ffmpeg"
    assert "-vf" in command
    assert "setpts=PTS/0.5" in command[command.index("-vf") + 1]
    assert "-af" in command
    assert "atempo=0.5" in command[command.index("-af") + 1]
    assert command[-1] == "output.mp4"


def test_executor_rejects_operations_without_real_local_adapter() -> None:
    with pytest.raises(MediaExecutionError, match="background_segmentation"):
        build_ffmpeg_command(
            "input.mp4",
            "output.mp4",
            [EditNode("background_segmentation", {"mode": "subject"}, "vision")],
        )


def test_executor_never_allows_in_place_overwrite() -> None:
    with pytest.raises(ValueError, match="different"):
        build_ffmpeg_command(Path("same.mp4"), Path("same.mp4"), [])
