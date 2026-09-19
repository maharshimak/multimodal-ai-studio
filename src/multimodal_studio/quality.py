import json
from dataclasses import asdict, dataclass
from hashlib import sha256

from multimodal_studio.planner import STAGE_ORDER, EditNode, validate


@dataclass(frozen=True, slots=True)
class PlanDiagnostics:
    fingerprint: str
    operation_count: int
    stages: tuple[str, ...]
    warnings: tuple[str, ...]


def plan_fingerprint(nodes: list[EditNode]) -> str:
    payload = json.dumps(
        [asdict(node) for node in nodes],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return sha256(payload).hexdigest()


def analyze_plan(nodes: list[EditNode], *, max_operations: int = 20) -> PlanDiagnostics:
    if isinstance(max_operations, bool) or not isinstance(max_operations, int) or max_operations <= 0:
        raise ValueError("max_operations must be a positive integer")
    validate(nodes)
    if len(nodes) > max_operations:
        raise ValueError(f"Edit plan exceeds {max_operations} operations")

    stage_indexes: list[int] = []
    stages: list[str] = []
    for node in nodes:
        if not node.operation.strip():
            raise ValueError("Edit operations must have a name")
        if node.stage not in STAGE_ORDER:
            raise ValueError(f"Unknown edit stage: {node.stage}")
        try:
            json.dumps(node.parameters, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Parameters for {node.operation} are not JSON-safe") from exc
        stage_indexes.append(STAGE_ORDER[node.stage])
        stages.append(node.stage)

    if stage_indexes != sorted(stage_indexes):
        raise ValueError("Edit stages must follow the deterministic pipeline order")

    warnings = ("Plan contains no edit operations.",) if not nodes else ()
    return PlanDiagnostics(
        fingerprint=plan_fingerprint(nodes),
        operation_count=len(nodes),
        stages=tuple(stages),
        warnings=warnings,
    )
