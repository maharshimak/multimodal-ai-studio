import pytest

from multimodal_studio.executor import FFmpegExecutor, build_ffmpeg_command
from multimodal_studio.planner import EditNode, to_json, validate


@pytest.mark.parametrize(
    "start,end",
    [(float("nan"), 10), (0, float("nan")), (0, float("inf"))],
)
def test_nonfinite_trim_bounds_are_rejected_by_planning_and_command_export(start, end):
    nodes = [EditNode("trim", {"start_seconds": start, "end_seconds": end}, "temporal")]
    for action in (validate, to_json):
        with pytest.raises(ValueError, match="finite"):
            action(nodes)
    with pytest.raises(ValueError, match="finite"):
        build_ffmpeg_command("input.mp4", "output.mp4", nodes)


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), float("-inf")])
def test_executor_rejects_nonfinite_timeout_before_preflight(timeout):
    with pytest.raises(ValueError):
        FFmpegExecutor(timeout_seconds=timeout)


def test_finite_trim_and_timeout_keep_supported_behavior():
    nodes = [EditNode("trim", {"start_seconds": 0.5, "end_seconds": 2.5}, "temporal")]
    command = build_ffmpeg_command("input.mp4", "output.mp4", nodes)
    assert "trim=start=0.5:end=2.5" in command[command.index("-vf") + 1]
    assert FFmpegExecutor(timeout_seconds=0.5).timeout_seconds == 0.5
