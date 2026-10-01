import pytest

from multimodal_studio.budget import (
    MediaProfile,
    RenderBudget,
    RenderBudgetExceeded,
    enforce_render_budget,
)
from multimodal_studio.planner import EditNode, plan, validate


def test_empty_and_unknown_operations_fail_closed():
    with pytest.raises(RenderBudgetExceeded):
        enforce_render_budget([], MediaProfile(1920, 1080, 10, 30), RenderBudget())
    with pytest.raises(ValueError):
        validate([EditNode("magic", {}, "vision")])
    with pytest.raises(ValueError):
        plan("  ")



def test_remote_diffusion_models_require_pinned_revision():
    from multimodal_studio.ai import DiffusersImageGenerator

    with pytest.raises(ValueError, match="pinned revision"):
        DiffusersImageGenerator("example-org/example-model")
