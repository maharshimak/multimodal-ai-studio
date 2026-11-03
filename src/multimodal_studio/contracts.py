"""MAK'MA ``makma.v1`` execution contract for the multimodal studio.

This package has no Pydantic dependency, so the envelope is a frozen dataclass with
explicit validation of the contract invariants. Conformance with the shared JSON
Schema (``contracts/makma.v1.schema.json``) is enforced by ``tests/test_contracts.py``.

Operations
----------
``plan``            Validate a prompt or typed edit graph and build the canonical plan.
``execute``         Render with the local FFmpeg binary (side effects, approval gated).
``verify_artifact`` SHA-256 an output file and, where ffprobe exists, check its media.

All operations are ``deterministic_offline``: keyword/regex planning, arithmetic and
the local FFmpeg binary. No model inference is involved.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version
from pathlib import Path
from typing import Any

from multimodal_studio.artifacts import sha256_file, verify_artifact
from multimodal_studio.budget import (
    MediaProfile,
    RenderBudget,
    RenderBudgetExceeded,
    enforce_output_budget,
    enforce_render_budget,
)
from multimodal_studio.executor import (
    FFmpegExecutor,
    FFmpegUnavailableError,
    MediaExecutionError,
    UnsupportedOperationError,
    build_filter_chains,
    probe_media,
)
from multimodal_studio.planner import (
    EditNode,
    PlanValidationError,
    canonical_order,
    plan,
    validate,
)
from multimodal_studio.quality import plan_fingerprint
from multimodal_studio.timeline import MediaPlanError, parse_frame_rate, project_output

CONTRACT_VERSION = "makma.v1"
SYSTEM = "multimodal-ai-studio"
WORKSPACE_ENV = "MULTIMODAL_STUDIO_WORKSPACE"
EXECUTION_MODE = "deterministic_offline"

_STATUSES = {"ok", "error", "blocked", "pending_approval"}
_MODES = {"deterministic_offline", "local_model", "remote_model"}
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _version() -> str:
    try:
        return _package_version("multimodal-ai-studio")
    except PackageNotFoundError:  # pragma: no cover - source checkout without install
        return "0.0.0+unknown"


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class ContractError:
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _CODE_RE.match(self.code):
            raise ValueError(f"invalid error code: {self.code!r}")


@dataclass(frozen=True, slots=True)
class Provenance:
    kind: str
    id: str
    sha256: str | None = None
    span: tuple[int, int] | None = None
    uri: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"document", "chunk", "artifact", "dataset", "model", "query", "record"}:
            raise ValueError(f"invalid provenance kind: {self.kind!r}")
        if not self.id:
            raise ValueError("provenance id is required")
        if self.sha256 is not None and not _HEX64.match(self.sha256):
            raise ValueError("provenance sha256 must be 64 lowercase hex characters")


@dataclass(frozen=True, slots=True)
class Policy:
    decision: str
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.decision not in {"allow", "deny", "requires_approval"}:
            raise ValueError(f"invalid policy decision: {self.decision!r}")


@dataclass(frozen=True, slots=True)
class Envelope:
    operation: str
    run_id: str
    correlation_id: str
    status: str
    data: Any
    error: ContractError | None
    provenance: tuple[Provenance, ...]
    policy: Policy | None
    started_at: str
    duration_ms: float
    trace_id: str = field(default_factory=lambda: secrets.token_hex(16))
    span_id: str = field(default_factory=lambda: secrets.token_hex(8))
    execution_mode: str = EXECUTION_MODE
    contract_version: str = CONTRACT_VERSION
    system: str = SYSTEM

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"invalid status: {self.status!r}")
        if self.execution_mode not in _MODES:
            raise ValueError(f"invalid execution_mode: {self.execution_mode!r}")
        if (self.status == "ok") != (self.error is None) and self.status != "pending_approval":
            raise ValueError("status 'ok' requires error == null and vice versa")
        if self.status in {"error", "blocked"} and self.data is not None:
            raise ValueError("error/blocked envelopes must have data == null")
        if self.status == "pending_approval" and (
            self.policy is None or self.policy.decision != "requires_approval"
        ):
            raise ValueError("pending_approval requires policy.decision == 'requires_approval'")
        if not (1 <= len(self.run_id) <= 128 and 1 <= len(self.correlation_id) <= 128):
            raise ValueError("run_id and correlation_id must be 1-128 characters")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "system": self.system,
            "operation": self.operation,
            "run_id": self.run_id,
            "correlation_id": self.correlation_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "status": self.status,
            "execution_mode": self.execution_mode,
            "data": self.data,
            "error": asdict(self.error) if self.error else None,
            "provenance": [
                {**asdict(p), "span": list(p.span) if p.span is not None else None}
                for p in self.provenance
            ],
            "policy": (
                {"decision": self.policy.decision, "reasons": list(self.policy.reasons)}
                if self.policy
                else None
            ),
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
        }


class _OpFailure(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: str = "error",
        retryable: bool = False,
        details: dict[str, Any] | None = None,
        policy: Policy | None = None,
    ) -> None:
        super().__init__(message)
        self.error = ContractError(code, message[:2000], retryable, details or {})
        self.status = status
        self.policy = policy


@dataclass(slots=True)
class _Result:
    data: Any
    provenance: list[Provenance] = field(default_factory=list)
    status: str = "ok"
    policy: Policy | None = None


# --------------------------------------------------------------------------- input


def _invalid(message: str, **details: Any) -> _OpFailure:
    return _OpFailure("INVALID_INPUT", message, details=details)


def _check_keys(payload: dict[str, Any], allowed: set[str], where: str = "payload") -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise _invalid(f"Unknown fields in {where}: {', '.join(unknown)}", fields=unknown)


def _number(value: Any, name: str, *, integer: bool = False) -> float | int:
    if isinstance(value, bool) or not isinstance(value, int if integer else (int, float)):
        raise _invalid(f"{name} must be {'an integer' if integer else 'a number'}")
    return value


def _nodes_from_payload(payload: dict[str, Any]) -> list[EditNode]:
    has_prompt = "prompt" in payload
    has_nodes = "nodes" in payload
    if has_prompt == has_nodes:
        raise _invalid("Provide exactly one of 'prompt' or 'nodes'.")
    try:
        if has_prompt:
            prompt = payload["prompt"]
            if not isinstance(prompt, str):
                raise _invalid("prompt must be a string")
            return plan(prompt)
        raw = payload["nodes"]
        if not isinstance(raw, list) or len(raw) > 32:
            raise _invalid("nodes must be a list of at most 32 objects")
        nodes: list[EditNode] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise _invalid(f"nodes[{index}] must be an object")
            _check_keys(item, {"operation", "parameters", "stage"}, f"nodes[{index}]")
            operation, stage = item.get("operation"), item.get("stage")
            parameters = item.get("parameters", {})
            if not isinstance(operation, str) or not isinstance(stage, str):
                raise _invalid(f"nodes[{index}] needs string 'operation' and 'stage'")
            if not isinstance(parameters, dict):
                raise _invalid(f"nodes[{index}].parameters must be an object")
            nodes.append(EditNode(operation, dict(parameters), stage))
        ordered = canonical_order(nodes)
        validate(ordered)
        return ordered
    except PlanValidationError as error:
        raise _OpFailure("PLAN_INVALID", str(error)) from error
    except ValueError as error:  # prompt length/emptiness from plan()
        raise _invalid(str(error)) from error


def _media_from_payload(raw: Any) -> MediaProfile:
    if not isinstance(raw, dict):
        raise _invalid("media must be an object")
    _check_keys(raw, {"width", "height", "duration_seconds", "fps"}, "media")
    for key in ("width", "height", "duration_seconds", "fps"):
        if key not in raw:
            raise _invalid(f"media.{key} is required")
    fps = parse_frame_rate(raw["fps"])
    if fps is None:
        raise _invalid("media.fps must be a positive frame rate such as 25 or '30000/1001'")
    try:
        return MediaProfile(
            width=_number(raw["width"], "media.width", integer=True),  # type: ignore[arg-type]
            height=_number(raw["height"], "media.height", integer=True),  # type: ignore[arg-type]
            duration_seconds=_number(raw["duration_seconds"], "media.duration_seconds"),
            fps=float(fps),
        )
    except (TypeError, ValueError) as error:
        raise _invalid(str(error)) from error


def _budget_from_payload(raw: Any) -> RenderBudget:
    if raw is None:
        return RenderBudget()
    if not isinstance(raw, dict):
        raise _invalid("budget must be an object")
    allowed = {"max_operations", "max_megapixel_frames", "max_output_seconds", "max_output_pixels"}
    _check_keys(raw, allowed, "budget")
    try:
        return RenderBudget(**raw)
    except (TypeError, ValueError) as error:
        raise _invalid(str(error)) from error


def _workspace_root() -> Path:
    configured = os.environ.get(WORKSPACE_ENV)
    return Path(configured).resolve() if configured else Path.cwd().resolve()


def _workspace_path(value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise _invalid(f"{name} must be a non-empty path string")
    root = _workspace_root()
    candidate = Path(value)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise _OpFailure(
            "PATH_OUTSIDE_WORKSPACE",
            f"{name} resolves outside the configured workspace ({WORKSPACE_ENV}).",
            status="blocked",
            policy=Policy("deny", (f"{name} outside workspace",)),
        )
    return resolved


def _node_dicts(nodes: list[EditNode]) -> list[dict[str, Any]]:
    return [asdict(node) for node in nodes]


def _plan_provenance(payload: dict[str, Any], nodes: list[EditNode]) -> list[Provenance]:
    items: list[Provenance] = []
    if "prompt" in payload:
        items.append(
            Provenance(
                "query", "prompt", hashlib.sha256(payload["prompt"].encode("utf-8")).hexdigest()
            )
        )
    items.append(Provenance("record", "edit_plan", plan_fingerprint(nodes)))
    return items


# --------------------------------------------------------------------------- operations


def _op_plan(payload: dict[str, Any]) -> _Result:
    _check_keys(payload, {"prompt", "nodes", "media", "budget"})
    nodes = _nodes_from_payload(payload)
    budget = _budget_from_payload(payload.get("budget"))
    try:
        video, audio = build_filter_chains(nodes)
        unsupported: list[str] = []
    except UnsupportedOperationError as error:
        video, audio, unsupported = [], [], error.operations
    data: dict[str, Any] = {
        "nodes": _node_dicts(nodes),
        "fingerprint": plan_fingerprint(nodes),
        "operation_count": len(nodes),
        "executable": bool(nodes) and not unsupported,
        "unsupported_operations": unsupported,
        "ffmpeg_filters": {"video": video, "audio": audio} if not unsupported else None,
        "estimate": None,
        "output": None,
    }
    provenance = _plan_provenance(payload, nodes)
    if "media" in payload:
        media = _media_from_payload(payload["media"])
        try:
            if not nodes:
                raise RenderBudgetExceeded("No supported operations; nothing to render.")
            estimate = enforce_render_budget(nodes, media, budget)
            output = enforce_output_budget(nodes, media, budget)
        except RenderBudgetExceeded as error:
            raise _OpFailure(
                "BUDGET_EXCEEDED",
                str(error),
                status="blocked",
                policy=Policy("deny", (str(error),)),
            ) from error
        except MediaPlanError as error:
            raise _OpFailure("PLAN_INCOMPATIBLE_WITH_MEDIA", str(error)) from error
        data["estimate"] = asdict(estimate)
        data["output"] = output.as_dict()
    return _Result(data, provenance)


def _op_execute(payload: dict[str, Any]) -> _Result:
    _check_keys(
        payload,
        {"source_path", "destination_path", "prompt", "nodes", "approved", "timeout_seconds",
         "budget"},
    )
    source = _workspace_path(payload.get("source_path"), "source_path")
    destination = _workspace_path(payload.get("destination_path"), "destination_path")
    if source == destination:
        raise _invalid("source_path and destination_path must be different files")
    approved = payload.get("approved", False)
    if not isinstance(approved, bool):
        raise _invalid("approved must be a boolean")
    timeout = payload.get("timeout_seconds", 600)
    _number(timeout, "timeout_seconds")
    if not 1 <= timeout <= 3600:
        raise _invalid("timeout_seconds must be between 1 and 3600")
    budget = _budget_from_payload(payload.get("budget"))
    nodes = _nodes_from_payload(payload)
    if not nodes:
        raise _OpFailure("PLAN_EMPTY", "The plan has no operations; nothing to render.")
    try:
        build_filter_chains(nodes)
    except UnsupportedOperationError as error:
        raise _OpFailure(
            "UNSUPPORTED_OPERATION",
            str(error),
            details={"operations": error.operations},
        ) from error

    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise _OpFailure(
            "FFMPEG_UNAVAILABLE",
            f"Required media binaries are not installed or not on PATH: {', '.join(missing)}.",
            details={"missing": missing},
        )
    if not source.is_file():
        raise _OpFailure("SOURCE_NOT_FOUND", "source_path does not exist or is not a file.")

    provenance = _plan_provenance(payload, nodes)
    if not approved:
        return _Result(
            {"nodes": _node_dicts(nodes), "fingerprint": plan_fingerprint(nodes)},
            provenance,
            status="pending_approval",
            policy=Policy(
                "requires_approval",
                ("execute writes a media file; resubmit with approved=true",),
            ),
        )

    source_sha = sha256_file(source)
    executor = FFmpegExecutor(timeout_seconds=float(timeout), render_budget=budget)
    try:
        output_path = executor.execute(source, destination, nodes)
        # The executor's preflight already rejected sources without dimensions,
        # duration or frame rate, so the projection below is well defined.
        source_probe = probe_media(source)
        projected = project_output(
            nodes,
            width=source_probe.width or 0,
            height=source_probe.height or 0,
            duration_seconds=source_probe.duration_seconds or 0,
            fps=source_probe.fps or 0,
        )
    except RenderBudgetExceeded as error:
        raise _OpFailure(
            "BUDGET_EXCEEDED", str(error), status="blocked", policy=Policy("deny", (str(error),))
        ) from error
    except MediaPlanError as error:
        raise _OpFailure("PLAN_INCOMPATIBLE_WITH_MEDIA", str(error)) from error
    except FFmpegUnavailableError as error:
        raise _OpFailure("FFMPEG_UNAVAILABLE", str(error)) from error
    except subprocess.TimeoutExpired as error:
        raise _OpFailure("EXECUTION_TIMEOUT", "FFmpeg render timed out.", retryable=True) from error
    except (MediaExecutionError, subprocess.SubprocessError) as error:
        raise _OpFailure("EXECUTION_FAILED", str(error)) from error

    verification = verify_artifact(
        output_path,
        expected_width=projected.width,
        expected_height=projected.height,
        require_video=True,
    )
    if verification.probe_status != "verified" or not verification.passed:
        raise _OpFailure(
            "OUTPUT_VERIFICATION_FAILED",
            "; ".join(verification.problems) or "output verification failed",
            details={"probe_status": verification.probe_status},
        )
    provenance.append(Provenance("artifact", "source", source_sha))
    provenance.append(Provenance("artifact", "output", verification.sha256))
    return _Result(
        {
            "nodes": _node_dicts(nodes),
            "fingerprint": plan_fingerprint(nodes),
            "output_path": str(output_path),
            "projected_output": projected.as_dict(),
            "artifact": verification.as_dict(),
        },
        provenance,
    )


def _op_verify_artifact(payload: dict[str, Any]) -> _Result:
    _check_keys(
        payload,
        {"path", "expected_sha256", "expected_width", "expected_height",
         "expected_duration_seconds", "duration_tolerance_seconds", "require_video",
         "require_audio"},
    )
    path = _workspace_path(payload.get("path"), "path")
    expected_sha = payload.get("expected_sha256")
    if expected_sha is not None and (
        not isinstance(expected_sha, str) or not _HEX64.match(expected_sha.lower())
    ):
        raise _invalid("expected_sha256 must be 64 hex characters")
    kwargs: dict[str, Any] = {}
    for key in ("expected_width", "expected_height"):
        if payload.get(key) is not None:
            kwargs[key] = _number(payload[key], key, integer=True)
    for key in ("expected_duration_seconds", "duration_tolerance_seconds"):
        if payload.get(key) is not None:
            kwargs[key] = _number(payload[key], key)
    for key in ("require_video", "require_audio"):
        if key in payload:
            if not isinstance(payload[key], bool):
                raise _invalid(f"{key} must be a boolean")
            kwargs[key] = payload[key]
    if not path.is_file():
        raise _OpFailure("ARTIFACT_NOT_FOUND", "path does not exist or is not a file.")
    try:
        verification = verify_artifact(path, expected_sha256=expected_sha, **kwargs)
    except ValueError as error:
        raise _invalid(str(error)) from error
    return _Result(
        verification.as_dict(),
        [Provenance("artifact", path.name, verification.sha256)],
    )


_PLAN_NODE_SCHEMA = {
    "type": "object",
    "required": ["operation", "stage"],
    "additionalProperties": False,
    "properties": {
        "operation": {"type": "string"},
        "stage": {"type": "string"},
        "parameters": {"type": "object"},
    },
}
_EDIT_INPUT = {
    "prompt": {"type": "string", "minLength": 1, "maxLength": 5000},
    "nodes": {"type": "array", "maxItems": 32, "items": _PLAN_NODE_SCHEMA},
}
_BUDGET_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "max_operations": {"type": "integer", "minimum": 1},
        "max_megapixel_frames": {"type": "number", "exclusiveMinimum": 0},
        "max_output_seconds": {"type": "number", "exclusiveMinimum": 0},
        "max_output_pixels": {"type": "integer", "minimum": 1},
    },
}

_OPERATIONS: dict[str, tuple[Callable[[dict[str, Any]], _Result], dict[str, Any]]] = {
    "plan": (
        _op_plan,
        {
            "name": "plan",
            "side_effects": False,
            "requires_approval": False,
            "timeout_s": 5,
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "oneOf": [{"required": ["prompt"]}, {"required": ["nodes"]}],
                "properties": {
                    **_EDIT_INPUT,
                    "media": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["width", "height", "duration_seconds", "fps"],
                        "properties": {
                            "width": {"type": "integer", "minimum": 1},
                            "height": {"type": "integer", "minimum": 1},
                            "duration_seconds": {"type": "number", "exclusiveMinimum": 0},
                            "fps": {"type": ["number", "string"]},
                        },
                    },
                    "budget": _BUDGET_SCHEMA,
                },
            },
        },
    ),
    "execute": (
        _op_execute,
        {
            "name": "execute",
            "side_effects": True,
            "requires_approval": True,
            "timeout_s": 3600,
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_path", "destination_path"],
                "oneOf": [{"required": ["prompt"]}, {"required": ["nodes"]}],
                "properties": {
                    **_EDIT_INPUT,
                    "source_path": {"type": "string", "minLength": 1},
                    "destination_path": {"type": "string", "minLength": 1},
                    "approved": {"type": "boolean", "default": False},
                    "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 3600},
                    "budget": _BUDGET_SCHEMA,
                },
            },
        },
    ),
    "verify_artifact": (
        _op_verify_artifact,
        {
            "name": "verify_artifact",
            "side_effects": False,
            "requires_approval": False,
            "timeout_s": 60,
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "expected_sha256": {"type": "string", "pattern": "^[0-9a-fA-F]{64}$"},
                    "expected_width": {"type": "integer", "minimum": 1},
                    "expected_height": {"type": "integer", "minimum": 1},
                    "expected_duration_seconds": {"type": "number", "minimum": 0},
                    "duration_tolerance_seconds": {"type": "number", "minimum": 0},
                    "require_video": {"type": "boolean"},
                    "require_audio": {"type": "boolean"},
                },
            },
        },
    ),
}


def capabilities() -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "system": SYSTEM,
        "version": _version(),
        "operations": [json.loads(json.dumps(spec)) for _, spec in _OPERATIONS.values()],
    }


def _safe_operation_name(operation: Any) -> str:
    if isinstance(operation, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", operation):
        return operation
    return "unknown"


def run_operation(
    operation: str,
    payload: dict[str, Any],
    *,
    run_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Run a makma.v1 operation in-process and return the envelope as a dict."""
    started = datetime.now(UTC)
    clock = time.perf_counter()
    rid = run_id if isinstance(run_id, str) and 1 <= len(run_id) <= 128 else uuid.uuid4().hex
    cid = (
        correlation_id
        if isinstance(correlation_id, str) and 1 <= len(correlation_id) <= 128
        else rid
    )

    status, data, error, provenance, policy = "ok", None, None, (), None
    entry = _OPERATIONS.get(operation) if isinstance(operation, str) else None
    try:
        if entry is None:
            raise _OpFailure("UNKNOWN_OPERATION", f"Unknown operation: {str(operation)[:64]!r}")
        if not isinstance(payload, dict):
            raise _invalid("payload must be a JSON object")
        result = entry[0](payload)
        status, data, provenance, policy = (
            result.status,
            result.data,
            tuple(result.provenance),
            result.policy,
        )
    except _OpFailure as failure:
        status, error, policy = failure.status, failure.error, failure.policy

    envelope = Envelope(
        operation=_safe_operation_name(operation),
        run_id=rid,
        correlation_id=cid,
        status=status,
        data=data,
        error=error,
        provenance=provenance,
        policy=policy,
        started_at=started.isoformat().replace("+00:00", "Z"),
        duration_ms=round((time.perf_counter() - clock) * 1000, 3),
    )
    return envelope.to_dict()
