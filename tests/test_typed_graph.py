import math

import pytest

from multimodal_studio.executor import (
    UnsupportedOperationError,
    build_ffmpeg_command,
    build_filter_chains,
)
from multimodal_studio.planner import (
    OPERATION_ORDER,
    PARAMETER_SCHEMA,
    STAGE_ORDER,
    EditNode,
    PlanValidationError,
    canonical_order,
    plan,
    validate,
)


def test_trim_precedes_retime_so_trim_bounds_use_the_source_timeline() -> None:
    # Regression: alphabetical ordering put retime before trim, so
    # "trim 0s to 10s, speed 2x" selected source seconds 0-20.
    nodes = plan("trim 0s to 10s, speed 2x")
    assert [n.operation for n in nodes] == ["trim", "retime"]

    command = build_ffmpeg_command("in.mp4", "out.mp4", nodes)
    video = command[command.index("-vf") + 1]
    audio = command[command.index("-af") + 1]
    assert video.index("trim=start=0:end=10") < video.index("setpts=PTS/2")
    assert audio.index("atrim=start=0:end=10") < audio.index("atempo=2")


def test_command_order_is_canonical_regardless_of_input_order() -> None:
    nodes = [
        EditNode("volume", {"gain_db": -3}, "audio"),
        EditNode("retime", {"speed": 1.5}, "temporal"),
        EditNode("resize", {"width": 640, "height": 360}, "vision"),
        EditNode("trim", {"start_seconds": 1, "end_seconds": 4}, "temporal"),
        EditNode("crop", {"width": 1280, "height": 720, "x": 0, "y": 0}, "vision"),
    ]
    forward = build_filter_chains(nodes)
    assert forward == build_filter_chains(list(reversed(nodes)))
    video, audio = forward
    assert [f.split("=")[0] for f in video] == ["crop", "scale", "trim", "setpts"]
    assert audio[0].startswith("atrim") and audio[-1].startswith("volume")


def test_canonical_order_is_a_total_order_consistent_with_stages() -> None:
    names = list(OPERATION_ORDER)
    ranks = [(STAGE_ORDER[OPERATION_ORDER[n][0]], OPERATION_ORDER[n][1]) for n in names]
    assert len(set(ranks)) == len(ranks)
    assert set(PARAMETER_SCHEMA) == set(OPERATION_ORDER)
    nodes = [EditNode(n, {}, OPERATION_ORDER[n][0]) for n in reversed(names)]
    ordered = canonical_order(nodes)
    assert [STAGE_ORDER[n.stage] for n in ordered] == sorted(STAGE_ORDER[n.stage] for n in nodes)


@pytest.mark.parametrize(
    "node",
    [
        # Fractional pixels used to be truncated silently (1920.9 -> 1920).
        EditNode("resize", {"width": 1920.9, "height": 1080}, "vision"),
        EditNode("resize", {"width": True, "height": 1080}, "vision"),
        EditNode("resize", {"width": "1920", "height": 1080}, "vision"),
        EditNode("resize", {"width": 1920}, "vision"),
        # Unknown parameters used to be accepted and ignored.
        EditNode("resize", {"width": 1920, "height": 1080, "filter": "x"}, "vision"),
        # None used to raise an untyped TypeError.
        EditNode("volume", {"gain_db": None}, "audio"),
        EditNode("volume", {"gain_db": math.nan}, "audio"),
        EditNode("retime", {"speed": math.inf}, "temporal"),
        EditNode("crop", {"width": 100, "height": 100, "x": -1, "y": 0}, "vision"),
        EditNode("color_grade", {"preset": "unknown"}, "color"),
        EditNode("audio_denoise", {"strength": 1.5}, "audio"),
        EditNode("trim", {"start_seconds": 5, "end_seconds": 5}, "temporal"),
        EditNode("trim", {"start_seconds": 0}, "temporal"),
        EditNode("magic", {}, "vision"),
        EditNode("resize", {"width": 640, "height": 360}, "color"),
    ],
)
def test_invalid_nodes_raise_typed_validation_error(node: EditNode) -> None:
    with pytest.raises(PlanValidationError):
        validate([node])
    # PlanValidationError stays a ValueError for backwards compatibility.
    assert issubclass(PlanValidationError, ValueError)


def test_integral_floats_are_accepted_for_integer_parameters() -> None:
    validate([EditNode("resize", {"width": 1920.0, "height": 1080}, "vision")])


def test_unsupported_operations_fail_with_typed_error_listing_them() -> None:
    nodes = plan("subtitles, replace background, cinematic")
    with pytest.raises(UnsupportedOperationError) as raised:
        build_filter_chains(nodes)
    assert raised.value.operations == ["background_segmentation", "subtitles"]


def test_plan_is_deterministic() -> None:
    prompt = "captions, slow motion, crop 640x480 at 10,20, volume -6 dB, denoise"
    assert plan(prompt) == plan(prompt)
