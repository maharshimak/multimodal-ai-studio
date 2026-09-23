import json
import re
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

_TRIM_RE = re.compile(
    r"\btrim(?:\s+from)?\s+(\d+(?:\.\d+)?)\s*s?(?:ec(?:ond)?s?)?\s+"
    r"(?:to|until|-)\s*(\d+(?:\.\d+)?)\s*s?(?:ec(?:ond)?s?)?",
    re.IGNORECASE,
)
_RESIZE_RE = re.compile(r"\bresize(?:\s+to)?\s+(\d{2,4})\s*[x×]\s*(\d{2,4})\b", re.IGNORECASE)
_CROP_RE = re.compile(
    r"\bcrop(?:\s+to)?\s+(\d{2,4})\s*[x×]\s*(\d{2,4})"
    r"(?:\s+(?:at|from)\s+(\d{1,4})\s*[,x:]\s*(\d{1,4}))?",
    re.IGNORECASE,
)
_VOLUME_RE = re.compile(
    r"\b(?:volume|gain)(?:\s+(?:to|by))?\s*([+-]?\d+(?:\.\d+)?)\s*dB\b",
    re.IGNORECASE,
)
_SPEED_RE = re.compile(
    r"\b(?:speed|retime)(?:\s+(?:to|at))?\s*(0\.5|0\.\d+|1(?:\.\d+)?|2(?:\.0+)?)\s*x\b",
    re.IGNORECASE,
)


def _parameterized_nodes(prompt: str) -> list[EditNode]:
    nodes: list[EditNode] = []

    trim_match = _TRIM_RE.search(prompt)
    if trim_match:
        nodes.append(
            EditNode(
                "trim",
                {
                    "start_seconds": float(trim_match.group(1)),
                    "end_seconds": float(trim_match.group(2)),
                },
                "temporal",
            )
        )

    resize_match = _RESIZE_RE.search(prompt)
    if resize_match:
        nodes.append(
            EditNode(
                "resize",
                {
                    "width": int(resize_match.group(1)),
                    "height": int(resize_match.group(2)),
                },
                "vision",
            )
        )

    crop_match = _CROP_RE.search(prompt)
    if crop_match:
        nodes.append(
            EditNode(
                "crop",
                {
                    "width": int(crop_match.group(1)),
                    "height": int(crop_match.group(2)),
                    "x": int(crop_match.group(3) or 0),
                    "y": int(crop_match.group(4) or 0),
                },
                "vision",
            )
        )

    volume_match = _VOLUME_RE.search(prompt)
    if volume_match:
        nodes.append(
            EditNode(
                "volume",
                {"gain_db": float(volume_match.group(1))},
                "audio",
            )
        )

    speed_match = _SPEED_RE.search(prompt)
    if speed_match:
        nodes.append(
            EditNode(
                "retime",
                {"speed": float(speed_match.group(1))},
                "temporal",
            )
        )

    return nodes


def plan(prompt: str) -> list[EditNode]:
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 5000:
        raise ValueError("A non-empty edit request of at most 5000 characters is required.")

    lower = prompt.lower()
    nodes = [
        deepcopy(node)
        for keys, node in KEYWORDS
        if any(key in lower for key in keys)
        and not (node.operation == "background_segmentation" and "background noise" in lower)
    ]
    nodes.extend(_parameterized_nodes(prompt))

    # A parameterized instruction is more specific than a keyword default.
    deduped: dict[str, EditNode] = {}
    for node in nodes:
        deduped[node.operation] = node

    ordered = sorted(deduped.values(), key=lambda n: (STAGE_ORDER[n.stage], n.operation))
    validate(ordered)
    return ordered


def validate(nodes: list[EditNode]) -> None:
    supported = {node.operation: node.stage for _, node in KEYWORDS}
    supported.update(
        {
            "grade": "color",
            "captions": "overlay",
            "trim": "temporal",
            "resize": "vision",
            "crop": "vision",
            "volume": "audio",
        }
    )
    for node in nodes:
        if node.operation not in supported or node.stage != supported[node.operation]:
            raise ValueError("Unsupported operation or incorrect stage.")

        if node.operation == "trim":
            start = float(node.parameters.get("start_seconds", -1))
            end = float(node.parameters.get("end_seconds", -1))
            if start < 0 or end <= start:
                raise ValueError("Trim requires 0 <= start < end.")
        elif node.operation in {"resize", "crop"}:
            width = int(node.parameters.get("width", 0))
            height = int(node.parameters.get("height", 0))
            if not 16 <= width <= 7680 or not 16 <= height <= 4320:
                raise ValueError("Media dimensions must be between 16x16 and 7680x4320.")
        elif node.operation == "volume":
            gain_db = float(node.parameters.get("gain_db", 0.0))
            if not -60.0 <= gain_db <= 24.0:
                raise ValueError("Volume gain must be between -60 dB and +24 dB.")
        elif node.operation == "retime":
            speed = float(node.parameters.get("speed", 1.0))
            if not 0.5 <= speed <= 2.0:
                raise ValueError("Retime speed must be between 0.5x and 2.0x.")

    operations = [n.operation for n in nodes]
    if len(operations) != len(set(operations)):
        raise ValueError("Duplicate operations are not allowed.")


def to_json(nodes: list[EditNode]) -> str:
    validate(nodes)
    return json.dumps([asdict(n) for n in nodes], indent=2)
