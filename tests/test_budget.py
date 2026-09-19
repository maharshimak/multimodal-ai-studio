import pytest

from multimodal_studio.budget import (
    MediaProfile,
    RenderBudget,
    RenderBudgetExceeded,
    enforce_render_budget,
    estimate_render,
)
from multimodal_studio.planner import EditNode


def test_render_estimate_accounts_for_media_and_operation_complexity() -> None:
    media = MediaProfile(width=1920, height=1080, duration_seconds=10, fps=30)
    nodes = [
        EditNode("background_segmentation", {"mode": "subject"}, "vision"),
        EditNode("color_grade", {"preset": "cinematic-teal"}, "color"),
    ]

    estimate = estimate_render(nodes, media)

    assert estimate.frame_count == 300
    assert estimate.operation_count == 2
    assert estimate.complexity_factor == pytest.approx(4.6)
    assert estimate.weighted_megapixel_frames > estimate.megapixel_frames


def test_render_budget_blocks_excessive_workload() -> None:
    media = MediaProfile(width=3840, height=2160, duration_seconds=600, fps=60)
    nodes = [EditNode("background_segmentation", {}, "vision")]

    with pytest.raises(RenderBudgetExceeded, match="megapixel-frames"):
        enforce_render_budget(
            nodes,
            media,
            RenderBudget(max_operations=8, max_megapixel_frames=1_000),
        )


def test_render_budget_accepts_preview_workload() -> None:
    media = MediaProfile(width=640, height=360, duration_seconds=5, fps=24)
    nodes = [EditNode("color_grade", {}, "color")]

    estimate = enforce_render_budget(nodes, media, RenderBudget())

    assert estimate.operation_count == 1
