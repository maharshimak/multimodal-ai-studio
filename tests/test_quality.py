import pytest

from multimodal_studio.planner import EditNode
from multimodal_studio.quality import analyze_plan, plan_fingerprint


def test_plan_fingerprint_is_stable_for_parameter_key_order() -> None:
    first = [EditNode("grade", {"contrast": 1.1, "gamma": 0.9}, "color")]
    second = [EditNode("grade", {"gamma": 0.9, "contrast": 1.1}, "color")]
    assert plan_fingerprint(first) == plan_fingerprint(second)
    assert analyze_plan(first).operation_count == 1


def test_plan_rejects_stage_regressions() -> None:
    nodes = [
        EditNode("captions", {}, "overlay"),
        EditNode("grade", {}, "color"),
    ]
    with pytest.raises(ValueError, match="pipeline order"):
        analyze_plan(nodes)
