import pytest

from multimodal_studio.routing import (
    CapabilityRouter,
    MediaTask,
    ModelCapability,
    RouteRequest,
)


def test_router_prefers_quality_when_requested():
    router = CapabilityRouter(
        [
            ModelCapability("fast", frozenset({MediaTask.TEXT_TO_VIDEO}), 4, 0.6, 0.95),
            ModelCapability("quality", frozenset({MediaTask.TEXT_TO_VIDEO}), 8, 0.95, 0.5),
        ]
    )
    route = router.route(RouteRequest(MediaTask.TEXT_TO_VIDEO, 8, prefer_quality=0.9))
    assert route.model.name == "quality"
    assert not route.offload_required


def test_router_can_use_offload_when_model_nearly_fits():
    router = CapabilityRouter(
        [ModelCapability("video", frozenset({MediaTask.IMAGE_TO_VIDEO}), 8, 0.9, 0.7)]
    )
    route = router.route(RouteRequest(MediaTask.IMAGE_TO_VIDEO, 4))
    assert route.offload_required


def test_router_rejects_unavailable_task():
    router = CapabilityRouter(
        [ModelCapability("image", frozenset({MediaTask.TEXT_TO_IMAGE}), 4, 0.8, 0.8)]
    )
    with pytest.raises(RuntimeError):
        router.route(RouteRequest(MediaTask.TEXT_TO_VIDEO, 8))
