from dataclasses import dataclass
from math import isfinite

from multimodal_studio.planner import EditNode, validate


class RenderBudgetExceeded(RuntimeError):
    """Raised when an edit plan exceeds an explicit render budget."""


@dataclass(frozen=True, slots=True)
class MediaProfile:
    width: int
    height: int
    duration_seconds: float
    fps: float

    def __post_init__(self) -> None:
        if isinstance(self.width, bool) or not isinstance(self.width, int) or self.width <= 0:
            raise ValueError("width must be a positive integer")
        if isinstance(self.height, bool) or not isinstance(self.height, int) or self.height <= 0:
            raise ValueError("height must be a positive integer")
        for name, value in (
            ("duration_seconds", self.duration_seconds),
            ("fps", self.fps),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number")
            if not isfinite(float(value)) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")


@dataclass(frozen=True, slots=True)
class RenderBudget:
    max_operations: int = 8
    max_megapixel_frames: float = 250_000.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_operations, bool)
            or not isinstance(self.max_operations, int)
            or self.max_operations <= 0
        ):
            raise ValueError("max_operations must be a positive integer")
        if (
            isinstance(self.max_megapixel_frames, bool)
            or not isinstance(self.max_megapixel_frames, (int, float))
        ):
            raise TypeError("max_megapixel_frames must be a number")
        if not isfinite(float(self.max_megapixel_frames)) or self.max_megapixel_frames <= 0:
            raise ValueError("max_megapixel_frames must be finite and positive")


@dataclass(frozen=True, slots=True)
class RenderEstimate:
    operation_count: int
    frame_count: int
    megapixel_frames: float
    complexity_factor: float
    weighted_megapixel_frames: float


_OPERATION_WEIGHTS = {
    "background_segmentation": 2.5,
    "retime": 1.3,
    "color_grade": 1.1,
    "audio_denoise": 0.2,
    "subtitles": 0.3,
}


def estimate_render(nodes: list[EditNode], media: MediaProfile) -> RenderEstimate:
    validate(nodes)
    frames = max(1, round(media.duration_seconds * media.fps))
    megapixels = (media.width * media.height) / 1_000_000
    complexity = 1.0 + sum(_OPERATION_WEIGHTS.get(node.operation, 0.5) for node in nodes)
    workload = megapixels * frames * complexity
    return RenderEstimate(
        operation_count=len(nodes),
        frame_count=frames,
        megapixel_frames=megapixels * frames,
        complexity_factor=complexity,
        weighted_megapixel_frames=workload,
    )


def enforce_render_budget(
    nodes: list[EditNode],
    media: MediaProfile,
    budget: RenderBudget,
) -> RenderEstimate:
    estimate = estimate_render(nodes, media)
    reasons: list[str] = []
    if estimate.operation_count > budget.max_operations:
        reasons.append(
            f"operations {estimate.operation_count} > maximum {budget.max_operations}"
        )
    if estimate.weighted_megapixel_frames > budget.max_megapixel_frames:
        reasons.append(
            "weighted megapixel-frames "
            f"{estimate.weighted_megapixel_frames:.1f} > maximum "
            f"{budget.max_megapixel_frames:.1f}"
        )
    if reasons:
        raise RenderBudgetExceeded("; ".join(reasons))
    return estimate
