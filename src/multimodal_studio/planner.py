import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from math import isfinite


class PlanValidationError(ValueError):
    """Raised when an edit graph is malformed: unknown operation, wrong stage,
    unexpected/missing parameters, wrong parameter types or out-of-range values."""


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
    r"\b(?:speed|retime)(?:\s+(?:to|at))?\s*(\d+(?:\.\d+)?)\s*x\b",
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


# Canonical position of every supported operation. Stages run in STAGE_ORDER; inside a
# stage the order is fixed so that semantics never depend on alphabetical accidents.
# In particular ``trim`` precedes ``retime``: trim bounds always refer to the *source*
# timeline, and crop offsets always refer to *source* pixels (crop precedes resize).
OPERATION_ORDER: dict[str, tuple[str, int]] = {
    "background_segmentation": ("vision", 0),
    "crop": ("vision", 1),
    "resize": ("vision", 2),
    "trim": ("temporal", 0),
    "retime": ("temporal", 1),
    "color_grade": ("color", 0),
    "grade": ("color", 1),
    "audio_denoise": ("audio", 0),
    "volume": ("audio", 1),
    "captions": ("overlay", 0),
    "subtitles": ("overlay", 1),
}

# Parameter schema per operation: name -> (kind, required, minimum, maximum | allowed values).
# kind is "int" (strict integer, bools rejected), "number" (finite int/float, bools
# rejected) or "enum" (one of the allowed strings).
_ParamSpec = tuple[str, bool, object, object]
PARAMETER_SCHEMA: dict[str, dict[str, _ParamSpec]] = {
    "background_segmentation": {"mode": ("enum", False, None, ("subject",))},
    "crop": {
        "width": ("int", True, 16, 7680),
        "height": ("int", True, 16, 4320),
        "x": ("int", False, 0, 7680),
        "y": ("int", False, 0, 4320),
    },
    "resize": {"width": ("int", True, 16, 7680), "height": ("int", True, 16, 4320)},
    "trim": {
        "start_seconds": ("number", True, 0.0, None),
        "end_seconds": ("number", True, 0.0, None),
    },
    "retime": {"speed": ("number", False, 0.5, 2.0)},
    "color_grade": {"preset": ("enum", False, None, ("cinematic-teal",))},
    "grade": {
        "contrast": ("number", False, 0.0, 4.0),
        "gamma": ("number", False, 0.0, 4.0),
        "saturation": ("number", False, 0.0, 4.0),
    },
    "audio_denoise": {"strength": ("number", False, 0.0, 1.0)},
    "volume": {"gain_db": ("number", True, -60.0, 24.0)},
    "captions": {"mode": ("enum", False, None, ("auto",))},
    "subtitles": {"mode": ("enum", False, None, ("auto",))},
}


def canonical_order(nodes: list[EditNode]) -> list[EditNode]:
    """Return nodes sorted into the canonical pipeline order (input is not mutated)."""
    for node in nodes:
        if node.operation not in OPERATION_ORDER:
            raise PlanValidationError(f"Unsupported operation: {node.operation!r}.")
    return sorted(
        nodes,
        key=lambda n: (STAGE_ORDER[OPERATION_ORDER[n.operation][0]], OPERATION_ORDER[n.operation][1]),
    )


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

    ordered = canonical_order(list(deduped.values()))
    validate(ordered)
    return ordered


def _check_parameter(operation: str, name: str, value: object, spec: _ParamSpec) -> None:
    kind, _required, low, high = spec
    label = f"{operation}.{name}"
    if kind == "enum":
        if not isinstance(value, str) or value not in high:  # type: ignore[operator]
            raise PlanValidationError(f"{label} must be one of {list(high)}.")  # type: ignore[call-overload]
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanValidationError(f"{label} must be a finite number.")
    if not isfinite(value):
        raise PlanValidationError(f"{label} must be a finite number.")
    if kind == "int" and not isinstance(value, int) and not float(value).is_integer():
        raise PlanValidationError(f"{label} must be an integer.")
    if low is not None and value < low:  # type: ignore[operator]
        raise PlanValidationError(f"{label} must be >= {low}.")
    if high is not None and value > high:  # type: ignore[operator]
        raise PlanValidationError(f"{label} must be <= {high}.")


def validate(nodes: list[EditNode]) -> None:
    """Validate an edit graph; raises :class:`PlanValidationError` (a ``ValueError``)."""
    if not isinstance(nodes, list):
        raise PlanValidationError("An edit graph must be a list of EditNode objects.")
    for node in nodes:
        if not isinstance(node, EditNode):
            raise PlanValidationError("An edit graph must be a list of EditNode objects.")
        if node.operation not in OPERATION_ORDER or node.stage != OPERATION_ORDER[node.operation][0]:
            raise PlanValidationError("Unsupported operation or incorrect stage.")
        if not isinstance(node.parameters, dict):
            raise PlanValidationError(f"{node.operation} parameters must be an object.")
        schema = PARAMETER_SCHEMA[node.operation]
        unknown = sorted(set(node.parameters) - set(schema), key=str)
        if unknown:
            raise PlanValidationError(
                f"Unknown parameters for {node.operation}: {', '.join(map(str, unknown))}."
            )
        for name, spec in schema.items():
            if name not in node.parameters:
                if spec[1]:
                    raise PlanValidationError(f"{node.operation}.{name} is required.")
                continue
            _check_parameter(node.operation, name, node.parameters[name], spec)

        if node.operation == "trim":
            start = node.parameters["start_seconds"]
            end = node.parameters["end_seconds"]
            if start < 0 or end <= start:  # type: ignore[operator]
                raise PlanValidationError("Trim requires 0 <= start < end.")

    operations = [n.operation for n in nodes]
    if len(operations) != len(set(operations)):
        raise PlanValidationError("Duplicate operations are not allowed.")


def to_json(nodes: list[EditNode]) -> str:
    validate(nodes)
    return json.dumps([asdict(n) for n in nodes], indent=2, allow_nan=False)
