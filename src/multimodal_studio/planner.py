import json
from copy import deepcopy
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EditNode:
    operation: str
    parameters: dict[str, object]
    stage: str


KEYWORDS: list[tuple[tuple[str, ...], EditNode]] = [
    (("slow motion", "slow-mo"), EditNode("retime", {"speed": 0.5}, "temporal")),
    (
        ("teal", "cinematic"),
        EditNode("color_grade", {"preset": "cinematic-teal"}, "color"),
    ),
    (("noise", "denoise"), EditNode("audio_denoise", {"strength": 0.7}, "audio")),
    (("subtitle", "captions"), EditNode("subtitles", {"mode": "auto"}, "overlay")),
    (
        ("remove background", "replace background", "background segmentation"),
        EditNode("background_segmentation", {"mode": "subject"}, "vision"),
    ),
]

STAGE_ORDER = {
    "vision": 0,
    "temporal": 1,
    "color": 2,
    "audio": 3,
    "overlay": 4,
}


def plan(prompt: str) -> list[EditNode]:
    lower = prompt.lower()
    nodes = [
        deepcopy(node)
        for keys, node in KEYWORDS
        if any(key in lower for key in keys)
        and not (
            node.operation == "background_segmentation" and "background noise" in lower
        )
    ]
    deduped = {node.operation: node for node in nodes}
    return sorted(deduped.values(), key=lambda n: STAGE_ORDER[n.stage])


def validate(nodes: list[EditNode]) -> None:
    operations = [n.operation for n in nodes]
    if len(operations) != len(set(operations)):
        raise ValueError("Duplicate operations are not allowed.")


def to_json(nodes: list[EditNode]) -> str:
    validate(nodes)
    return json.dumps([asdict(n) for n in nodes], indent=2)
