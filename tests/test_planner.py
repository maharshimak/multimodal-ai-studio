from multimodal_studio.planner import plan, to_json


def test_plan_orders_effects() -> None:
    nodes = plan("cinematic teal, slow motion, subtitles")
    assert [n.operation for n in nodes] == [
        "retime",
        "color_grade",
        "subtitles",
    ]


def test_export() -> None:
    assert '"operation": "audio_denoise"' in to_json(plan("remove background noise"))
