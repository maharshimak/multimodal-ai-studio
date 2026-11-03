"""Exact frame/duration arithmetic and plan-vs-media compatibility checks.

Frame rates are kept as :class:`fractions.Fraction` so NTSC rates such as
``30000/1001`` are never approximated. Durations given as floats are converted
through their shortest decimal representation (``Fraction(str(x))``, so ``0.1`` is
exactly 1/10), and every rounding decision is explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import ceil, floor, isfinite
from typing import Literal

from multimodal_studio.planner import EditNode, canonical_order, validate

Rounding = Literal["nearest", "floor", "ceil"]

# Upper bound for a plausible frame rate; rejects garbage such as "1000000/1".
MAX_FRAME_RATE = Fraction(1000)


class MediaPlanError(ValueError):
    """Raised when a valid edit graph cannot be applied to the given media."""


def parse_frame_rate(value: object) -> Fraction | None:
    """Parse an ffprobe-style frame rate (``"30000/1001"``, ``"25"``, ``29.97``).

    Returns ``None`` for absent/unknown values (``None``, ``""``, ``"0/0"``) and for
    anything that is not a finite rate in ``(0, MAX_FRAME_RATE]``.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Fraction):
        rate = value
    elif isinstance(value, int):
        rate = Fraction(value)
    elif isinstance(value, float):
        if not isfinite(value):
            return None
        rate = Fraction(str(value))
    elif isinstance(value, str):
        text = value.strip()
        if not text or text == "0/0":
            return None
        try:
            rate = Fraction(text)
        except (ValueError, ZeroDivisionError):
            return None
    else:
        return None
    if rate <= 0 or rate > MAX_FRAME_RATE:
        return None
    return rate


def _exact(seconds: float | Fraction, name: str = "seconds") -> Fraction:
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float, Fraction)):
        raise TypeError(f"{name} must be a number")
    if isinstance(seconds, float) and not isfinite(seconds):
        raise ValueError(f"{name} must be finite")
    if seconds < 0:
        raise ValueError(f"{name} must be non-negative")
    return Fraction(str(seconds)) if isinstance(seconds, float) else Fraction(seconds)


def _require_rate(fps: Fraction | float | str) -> Fraction:
    rate = parse_frame_rate(fps)
    if rate is None:
        raise ValueError(f"invalid frame rate: {fps!r}")
    return rate


def frame_count(
    duration_seconds: float | Fraction,
    fps: Fraction | float | str,
    *,
    rounding: Rounding = "nearest",
) -> int:
    """Number of frames covering ``duration_seconds`` at ``fps``.

    ``nearest`` rounds halves up (not banker's rounding), ``floor`` counts only
    complete frames, ``ceil`` counts every frame that starts inside the duration.
    """
    exact = _exact(duration_seconds, "duration_seconds") * _require_rate(fps)
    if rounding == "floor":
        return floor(exact)
    if rounding == "ceil":
        return ceil(exact)
    if rounding == "nearest":
        return floor(exact + Fraction(1, 2))
    raise ValueError(f"unknown rounding mode: {rounding!r}")


def frame_to_seconds(frame: int, fps: Fraction | float | str) -> Fraction:
    """Exact presentation time of frame index ``frame`` (0-based)."""
    if isinstance(frame, bool) or not isinstance(frame, int) or frame < 0:
        raise ValueError("frame must be a non-negative integer")
    return Fraction(frame) / _require_rate(fps)


def snap_to_frame(
    seconds: float | Fraction,
    fps: Fraction | float | str,
    *,
    rounding: Rounding = "nearest",
) -> Fraction:
    """Snap a timestamp onto the frame grid of ``fps``."""
    return frame_to_seconds(frame_count(seconds, fps, rounding=rounding), fps)


@dataclass(frozen=True, slots=True)
class OutputProfile:
    """What a plan produces from a given source, computed before any rendering.

    ``frame_count`` assumes the output keeps the source frame rate (FFmpeg's default
    for these filters). ``source_frames_decoded`` counts frames read up to the trim
    end, because filter-based trimming still decodes from the start of the file.
    """

    width: int
    height: int
    duration_seconds: Fraction
    frame_count: int
    source_frames_decoded: int

    def as_dict(self) -> dict[str, object]:
        return {
            "width": self.width,
            "height": self.height,
            "duration_seconds": float(self.duration_seconds),
            "frame_count": self.frame_count,
            "source_frames_decoded": self.source_frames_decoded,
        }


def project_output(
    nodes: list[EditNode],
    *,
    width: int,
    height: int,
    duration_seconds: float | Fraction,
    fps: Fraction | float | str,
) -> OutputProfile:
    """Apply a validated plan to source metadata and return the output profile.

    Raises :class:`MediaPlanError` when the plan cannot apply to this media, e.g. a
    trim that starts at or after the end of the source, or a crop window that falls
    outside the source frame. A trim end past the source end is clamped, which is
    what FFmpeg's ``trim`` filter does.
    """
    validate(nodes)
    for name, value in (("width", width), ("height", height)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    rate = _require_rate(fps)
    source_duration = _exact(duration_seconds, "duration_seconds")
    if source_duration == 0:
        raise MediaPlanError("Source media has zero duration.")

    out_w, out_h = width, height
    decoded_until = source_duration
    duration = source_duration
    for node in canonical_order(nodes):
        params = node.parameters
        if node.operation == "crop":
            crop_w, crop_h = int(params["width"]), int(params["height"])
            x, y = int(params.get("x", 0)), int(params.get("y", 0))
            if x + crop_w > out_w or y + crop_h > out_h:
                raise MediaPlanError(
                    f"Crop window {crop_w}x{crop_h}+{x}+{y} exceeds the {out_w}x{out_h} frame."
                )
            out_w, out_h = crop_w, crop_h
        elif node.operation == "resize":
            out_w, out_h = int(params["width"]), int(params["height"])
        elif node.operation == "trim":
            start = _exact(params["start_seconds"], "start_seconds")
            end = _exact(params["end_seconds"], "end_seconds")
            if start >= source_duration:
                raise MediaPlanError(
                    f"Trim start {float(start):g}s is not before the source end "
                    f"{float(source_duration):g}s."
                )
            end = min(end, source_duration)
            decoded_until = end
            duration = end - start
        elif node.operation == "retime":
            duration = duration / _exact(params.get("speed", 1.0), "speed")

    return OutputProfile(
        width=out_w,
        height=out_h,
        duration_seconds=duration,
        frame_count=max(1, frame_count(duration, rate)),
        source_frames_decoded=max(1, frame_count(decoded_until, rate, rounding="ceil")),
    )
