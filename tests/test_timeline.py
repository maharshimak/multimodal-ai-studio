import random
from fractions import Fraction

import pytest

from multimodal_studio.executor import _parse_frame_rate
from multimodal_studio.planner import EditNode
from multimodal_studio.timeline import (
    MediaPlanError,
    frame_count,
    frame_to_seconds,
    parse_frame_rate,
    project_output,
    snap_to_frame,
)

COMMON_RATES = [
    Fraction(24000, 1001),
    Fraction(24),
    Fraction(25),
    Fraction(30000, 1001),
    Fraction(30),
    Fraction(50),
    Fraction(60000, 1001),
    Fraction(60),
    Fraction(120),
]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("30000/1001", Fraction(30000, 1001)),
        ("24", Fraction(24)),
        ("29.97", Fraction(2997, 100)),
        (25, Fraction(25)),
        (23.976, Fraction(23976, 1000)),
        (Fraction(60000, 1001), Fraction(60000, 1001)),
    ],
)
def test_parse_frame_rate_is_exact(raw, expected) -> None:
    assert parse_frame_rate(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [None, "", "0/0", "1/0", "0", "-25", "abc", "inf", "nan", float("inf"), float("nan"), True,
     "1000001/1", [], 0],
)
def test_parse_frame_rate_rejects_unknown_or_invalid(raw) -> None:
    assert parse_frame_rate(raw) is None


def test_executor_frame_rate_parser_rejects_infinite_rates() -> None:
    # Regression: _parse_frame_rate("inf") used to return inf, which later failed
    # inside MediaProfile with an unrelated error.
    assert _parse_frame_rate("inf") is None
    assert _parse_frame_rate("30000/1001") == pytest.approx(29.97002997)


def test_ntsc_frame_count_is_exact() -> None:
    # One hour of 29.97 fps is 107892.107... frames, not 107892 or 108000.
    assert frame_count(3600, "30000/1001", rounding="floor") == 107892
    assert frame_count(3600, "30000/1001", rounding="ceil") == 107893
    assert frame_count(1001, "30000/1001") == 30000


def test_nearest_rounds_halves_up_not_to_even() -> None:
    assert frame_count(Fraction(1, 2), 1) == 1
    assert frame_count(Fraction(5, 2), 1) == 3  # round() would give 2
    assert frame_count(Fraction(3, 2), 1) == 2


def test_float_durations_use_their_decimal_value() -> None:
    # 0.1 s at 30 fps is exactly 3 frames; binary 0.1 is slightly above 1/10.
    assert frame_count(0.1, 30, rounding="ceil") == 3
    assert frame_count(0.3, 10, rounding="floor") == 3


def test_frame_arithmetic_properties_hold_for_random_inputs() -> None:
    rng = random.Random(20261103)
    for _ in range(2000):
        fps = rng.choice(COMMON_RATES)
        frame = rng.randrange(0, 10_000_000)
        seconds = frame_to_seconds(frame, fps)
        # Round trip: a frame's own timestamp maps back to that frame in every mode.
        for mode in ("nearest", "floor", "ceil"):
            assert frame_count(seconds, fps, rounding=mode) == frame
        assert snap_to_frame(seconds, fps) == seconds

        duration = Fraction(rng.randrange(0, 10**9), rng.randrange(1, 10**4))
        lo = frame_count(duration, fps, rounding="floor")
        mid = frame_count(duration, fps)
        hi = frame_count(duration, fps, rounding="ceil")
        assert lo <= mid <= hi <= lo + 1
        assert frame_to_seconds(lo, fps) <= duration <= frame_to_seconds(hi, fps)
        # Monotonic in duration.
        assert frame_count(duration + Fraction(1, 7), fps) >= mid


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), "3", True])
def test_frame_count_rejects_invalid_durations(bad) -> None:
    with pytest.raises((TypeError, ValueError)):
        frame_count(bad, 30)


def test_frame_count_rejects_unknown_rounding_and_bad_rate() -> None:
    with pytest.raises(ValueError):
        frame_count(1, 30, rounding="banker")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        frame_count(1, "0/0")


def _source(nodes, **overrides):
    media = {"width": 1920, "height": 1080, "duration_seconds": 60.0, "fps": "30000/1001"}
    media.update(overrides)
    return project_output(nodes, **media)


def test_projection_applies_trim_then_retime_on_the_source_timeline() -> None:
    out = _source(
        [
            EditNode("retime", {"speed": 2.0}, "temporal"),
            EditNode("trim", {"start_seconds": 10, "end_seconds": 30}, "temporal"),
        ]
    )
    assert out.duration_seconds == 10
    assert out.frame_count == frame_count(10, "30000/1001")
    assert out.source_frames_decoded == frame_count(30, "30000/1001", rounding="ceil")


def test_projection_clamps_trim_end_to_source_duration() -> None:
    out = _source([EditNode("trim", {"start_seconds": 50, "end_seconds": 500}, "temporal")])
    assert out.duration_seconds == 10


def test_projection_rejects_trim_starting_after_source_end() -> None:
    with pytest.raises(MediaPlanError, match="Trim start"):
        _source([EditNode("trim", {"start_seconds": 60, "end_seconds": 70}, "temporal")])


def test_projection_crops_in_source_pixels_then_resizes() -> None:
    out = _source(
        [
            EditNode("resize", {"width": 640, "height": 640}, "vision"),
            EditNode("crop", {"width": 1080, "height": 1080, "x": 840, "y": 0}, "vision"),
        ]
    )
    assert (out.width, out.height) == (640, 640)


@pytest.mark.parametrize(
    "params",
    [
        {"width": 1921, "height": 1080, "x": 0, "y": 0},
        {"width": 1080, "height": 1080, "x": 841, "y": 0},
        {"width": 100, "height": 100, "x": 0, "y": 981},
    ],
)
def test_projection_rejects_crop_outside_frame(params) -> None:
    with pytest.raises(MediaPlanError, match="Crop window"):
        _source([EditNode("crop", params, "vision")])


def test_projection_slow_motion_extends_duration() -> None:
    out = _source([EditNode("retime", {"speed": 0.5}, "temporal")], duration_seconds=12.5, fps=24)
    assert out.duration_seconds == 25
    assert out.frame_count == 600
