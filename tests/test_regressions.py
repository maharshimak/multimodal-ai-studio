from multimodal_studio.planner import plan


def test_background_noise_is_not_visual_segmentation():
    assert [n.operation for n in plan("remove background noise")] == ["audio_denoise"]
    assert [n.operation for n in plan("replace background")] == [
        "background_segmentation"
    ]


def test_plans_do_not_share_mutable_parameters():
    first = plan("slow motion")
    first[0].parameters["speed"] = 99
    assert plan("slow motion")[0].parameters["speed"] == 0.5
