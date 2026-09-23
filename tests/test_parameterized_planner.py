import pytest

from multimodal_studio.planner import plan


def by_operation(prompt: str):
    return {node.operation: node for node in plan(prompt)}


def test_parameterized_edit_instructions_are_parsed():
    nodes = by_operation(
        "Trim from 5s to 12.5s, resize to 1920x1080, crop 1080x1080 at 20,30, "
        "volume +3 dB and speed 1.5x"
    )
    assert nodes["trim"].parameters == {"start_seconds": 5.0, "end_seconds": 12.5}
    assert nodes["resize"].parameters == {"width": 1920, "height": 1080}
    assert nodes["crop"].parameters == {"width": 1080, "height": 1080, "x": 20, "y": 30}
    assert nodes["volume"].parameters == {"gain_db": 3.0}
    assert nodes["retime"].parameters == {"speed": 1.5}


def test_parameterized_speed_overrides_slow_motion_default():
    nodes = by_operation("slow motion but retime to 0.75x")
    assert nodes["retime"].parameters == {"speed": 0.75}


@pytest.mark.parametrize(
    "prompt",
    [
        "trim 10s to 5s",
        "resize to 9999x1080",
        "volume +30 dB",
        "speed 0.25x",
    ],
)
def test_invalid_parameterized_requests_fail_closed(prompt: str):
    with pytest.raises(ValueError):
        plan(prompt)
