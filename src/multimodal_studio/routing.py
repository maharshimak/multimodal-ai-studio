from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MediaTask(str, Enum):
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_TO_IMAGE = "image_to_image"
    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_VIDEO = "image_to_video"
    TRANSCRIPTION = "transcription"


@dataclass(frozen=True, slots=True)
class ModelCapability:
    name: str
    tasks: frozenset[MediaTask]
    min_vram_gb: float
    quality_score: float
    speed_score: float
    local: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.tasks:
            raise ValueError("model name and at least one task are required")
        if self.min_vram_gb < 0:
            raise ValueError("min_vram_gb must be non-negative")
        for name, value in (("quality_score", self.quality_score), ("speed_score", self.speed_score)):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class RouteRequest:
    task: MediaTask
    available_vram_gb: float
    prefer_quality: float = 0.7
    require_local: bool = False

    def __post_init__(self) -> None:
        if self.available_vram_gb < 0:
            raise ValueError("available_vram_gb must be non-negative")
        if not 0 <= self.prefer_quality <= 1:
            raise ValueError("prefer_quality must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ModelRoute:
    model: ModelCapability
    score: float
    offload_required: bool


class CapabilityRouter:
    """Select the best compatible media model for the task and hardware budget."""

    def __init__(self, models: list[ModelCapability], *, offload_headroom: float = 0.5) -> None:
        if not models:
            raise ValueError("at least one model capability is required")
        if not 0 <= offload_headroom <= 1:
            raise ValueError("offload_headroom must be between 0 and 1")
        self.models = tuple(models)
        self.offload_headroom = offload_headroom

    def route(self, request: RouteRequest) -> ModelRoute:
        candidates: list[ModelRoute] = []
        for model in self.models:
            if request.task not in model.tasks:
                continue
            if request.require_local and not model.local:
                continue

            fits = model.min_vram_gb <= request.available_vram_gb
            can_offload = (
                model.local
                and request.available_vram_gb > 0
                and model.min_vram_gb * self.offload_headroom <= request.available_vram_gb
            )
            if not fits and not can_offload:
                continue

            quality_weight = request.prefer_quality
            speed_weight = 1.0 - quality_weight
            score = quality_weight * model.quality_score + speed_weight * model.speed_score
            if not fits:
                score -= 0.12

            candidates.append(
                ModelRoute(model=model, score=score, offload_required=not fits)
            )

        if not candidates:
            raise RuntimeError("no compatible model fits the requested task and hardware budget")
        return max(candidates, key=lambda route: (route.score, route.model.quality_score))
