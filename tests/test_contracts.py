import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import multimodal_studio.artifacts as artifacts_module
from multimodal_studio import contracts
from multimodal_studio.contracts import capabilities, run_operation
from multimodal_studio.executor import MediaProbe

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "contracts" / "makma.v1.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=Draft202012Validator.FORMAT_CHECKER)


def check(envelope: dict) -> dict:
    Draft202012Validator.check_schema(SCHEMA)
    errors = sorted(VALIDATOR.iter_errors(envelope), key=str)
    assert not errors, [e.message for e in errors]
    assert envelope["system"] == "multimodal-ai-studio"
    assert envelope["execution_mode"] == "deterministic_offline"
    json.dumps(envelope, allow_nan=False)
    return envelope


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv(contracts.WORKSPACE_ENV, str(tmp_path))
    return tmp_path


def _stub_binaries(monkeypatch, available: bool) -> None:
    monkeypatch.setattr(
        contracts.shutil, "which", lambda name: f"/usr/bin/{name}" if available else None
    )


def _stub_probe(monkeypatch, probe) -> None:
    monkeypatch.setattr(contracts, "probe_media", probe)
    monkeypatch.setattr(artifacts_module, "probe_media", probe)


def test_capabilities_declare_real_operations_with_valid_input_schemas() -> None:
    caps = capabilities()
    assert caps["contract_version"] == "makma.v1"
    assert caps["system"] == "multimodal-ai-studio"
    ops = {op["name"]: op for op in caps["operations"]}
    assert set(ops) == {"plan", "execute", "verify_artifact"}
    assert ops["execute"]["side_effects"] and ops["execute"]["requires_approval"]
    assert not ops["plan"]["side_effects"]
    for op in ops.values():
        Draft202012Validator.check_schema(op["input_schema"])
        assert op["timeout_s"] > 0


def test_plan_ok_envelope_is_schema_valid_and_deterministic() -> None:
    payload = {
        "prompt": "trim 0s to 10s, speed 2x, resize to 1280x720",
        "media": {"width": 1920, "height": 1080, "duration_seconds": 60, "fps": "30000/1001"},
    }
    first = check(run_operation("plan", payload, run_id="run-1", correlation_id="corr-1"))
    second = check(run_operation("plan", payload))
    assert first["status"] == "ok" and first["error"] is None
    assert first["run_id"] == "run-1" and first["correlation_id"] == "corr-1"
    assert second["correlation_id"] == second["run_id"]
    assert first["data"] == second["data"]
    data = first["data"]
    assert [n["operation"] for n in data["nodes"]] == ["resize", "trim", "retime"]
    assert data["executable"] is True
    assert data["output"] == {
        "width": 1280,
        "height": 720,
        "duration_seconds": 5.0,
        "frame_count": 150,
        "source_frames_decoded": 300,
    }
    prompt_hash = hashlib.sha256(payload["prompt"].encode()).hexdigest()
    query = {"kind": "query", "id": "prompt", "sha256": prompt_hash, "span": None, "uri": None}
    assert query in first["provenance"]
    assert any(p["sha256"] == data["fingerprint"] for p in first["provenance"])


def test_plan_from_typed_nodes_reports_unsupported_operations() -> None:
    nodes = [
        {"operation": "subtitles", "stage": "overlay", "parameters": {"mode": "auto"}},
        {"operation": "volume", "stage": "audio", "parameters": {"gain_db": 2}},
    ]
    env = check(run_operation("plan", {"nodes": nodes}))
    assert env["status"] == "ok"
    assert env["data"]["executable"] is False
    assert env["data"]["unsupported_operations"] == ["subtitles"]
    assert env["data"]["ffmpeg_filters"] is None


SMALL_MEDIA = {"width": 640, "height": 360, "duration_seconds": 10, "fps": 25}


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({}, "INVALID_INPUT"),
        ({"prompt": "slow motion", "nodes": []}, "INVALID_INPUT"),
        ({"prompt": 3}, "INVALID_INPUT"),
        ({"prompt": "   "}, "INVALID_INPUT"),
        ({"prompt": "slow motion", "extra": 1}, "INVALID_INPUT"),
        ({"prompt": "slow motion", "media": {"width": 10}}, "INVALID_INPUT"),
        ({"prompt": "slow motion", "media": {**SMALL_MEDIA, "fps": "0/0"}}, "INVALID_INPUT"),
        ({"prompt": "slow motion", "media": {**SMALL_MEDIA, "width": 1.5}}, "INVALID_INPUT"),
        ({"prompt": "slow motion", "budget": {"max_operations": 0}}, "INVALID_INPUT"),
        ({"prompt": "volume +30 dB"}, "PLAN_INVALID"),
        (
            {
                "nodes": [
                    {
                        "operation": "resize",
                        "stage": "vision",
                        "parameters": {"width": 1920.5, "height": 1080},
                    }
                ]
            },
            "PLAN_INVALID",
        ),
        ({"nodes": [{"operation": "magic", "stage": "vision"}]}, "PLAN_INVALID"),
        ({"prompt": "trim 100s to 120s", "media": SMALL_MEDIA}, "PLAN_INCOMPATIBLE_WITH_MEDIA"),
    ],
)
def test_plan_invalid_inputs_return_error_envelopes(payload, code) -> None:
    env = check(run_operation("plan", payload))
    assert env["status"] == "error"
    assert env["data"] is None
    assert env["error"]["code"] == code


def test_plan_over_budget_is_blocked_with_deny_policy() -> None:
    env = check(
        run_operation(
            "plan",
            {
                "prompt": "replace background",
                "media": {"width": 3840, "height": 2160, "duration_seconds": 600, "fps": 60},
                "budget": {"max_megapixel_frames": 1000},
            },
        )
    )
    assert env["status"] == "blocked"
    assert env["error"]["code"] == "BUDGET_EXCEEDED"
    assert env["policy"]["decision"] == "deny"


@pytest.mark.parametrize("operation", ["render_everything", "PLAN", "", None])
def test_unknown_operation_is_rejected(operation) -> None:
    env = check(run_operation(operation, {}))  # type: ignore[arg-type]
    assert env["status"] == "error"
    assert env["error"]["code"] == "UNKNOWN_OPERATION"


def test_non_object_payload_is_invalid_input() -> None:
    env = check(run_operation("plan", ["slow motion"]))  # type: ignore[arg-type]
    assert env["error"]["code"] == "INVALID_INPUT"


def _execute(**overrides) -> dict:
    payload = {"source_path": "in.mp4", "destination_path": "out.mp4", "prompt": "slow motion"}
    payload.update(overrides)
    return check(run_operation("execute", payload))


def test_execute_without_ffmpeg_returns_ffmpeg_unavailable(workspace, monkeypatch) -> None:
    _stub_binaries(monkeypatch, available=False)
    (workspace / "in.mp4").write_bytes(b"synthetic")
    env = _execute(approved=True)
    assert env["status"] == "error"
    assert env["data"] is None
    assert env["error"]["code"] == "FFMPEG_UNAVAILABLE"
    assert env["error"]["details"] == {"missing": ["ffmpeg", "ffprobe"]}
    assert not (workspace / "out.mp4").exists()


def test_execute_rejects_paths_outside_workspace(workspace) -> None:
    env = _execute(destination_path="../escape.mp4")
    assert env["status"] == "blocked"
    assert env["error"]["code"] == "PATH_OUTSIDE_WORKSPACE"
    assert env["policy"]["decision"] == "deny"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"prompt": "add subtitles"}, "UNSUPPORTED_OPERATION"),
        ({"destination_path": "in.mp4"}, "INVALID_INPUT"),
        ({"approved": "yes"}, "INVALID_INPUT"),
        ({"timeout_seconds": 0}, "INVALID_INPUT"),
    ],
)
def test_execute_rejects_bad_requests_before_touching_media(workspace, overrides, code) -> None:
    env = _execute(**overrides)
    assert env["error"]["code"] == code


def test_execute_rejects_empty_plan(workspace) -> None:
    payload = {"source_path": "in.mp4", "destination_path": "out.mp4", "nodes": []}
    assert check(run_operation("execute", payload))["error"]["code"] == "PLAN_EMPTY"


def test_execute_requires_approval_before_rendering(workspace, monkeypatch) -> None:
    _stub_binaries(monkeypatch, available=True)
    (workspace / "in.mp4").write_bytes(b"synthetic")

    def must_not_run(*args, **kwargs):
        raise AssertionError("executor must not run without approval")

    monkeypatch.setattr(contracts.FFmpegExecutor, "execute", must_not_run)
    env = _execute()
    assert env["status"] == "pending_approval"
    assert env["policy"]["decision"] == "requires_approval"
    assert env["error"] is None
    assert not (workspace / "out.mp4").exists()


def test_execute_missing_source_is_reported(workspace, monkeypatch) -> None:
    _stub_binaries(monkeypatch, available=True)
    assert _execute(approved=True)["error"]["code"] == "SOURCE_NOT_FOUND"


def test_execute_happy_path_with_stubbed_ffmpeg_reports_verified_artifact(
    workspace, monkeypatch
) -> None:
    """Exercises the envelope wiring only: FFmpeg and ffprobe are stubbed here.

    The real render path is covered by tests/test_real_ffmpeg_contract.py, which
    runs only where ffmpeg/ffprobe are installed.
    """
    _stub_binaries(monkeypatch, available=True)
    (workspace / "in.mp4").write_bytes(b"synthetic source")

    def fake_execute(self, src, dst, nodes):
        Path(dst).write_bytes(b"synthetic output")
        return Path(dst)

    probes = {
        "in.mp4": MediaProbe(4.0, 1920, 1080, 25.0, "h264", "aac"),
        "out.mp4": MediaProbe(2.0, 640, 360, 25.0, "h264", "aac"),
    }
    monkeypatch.setattr(contracts.FFmpegExecutor, "execute", fake_execute)
    _stub_probe(monkeypatch, lambda path, **kwargs: probes[Path(path).name])
    env = _execute(approved=True, prompt="resize to 640x360, speed 2x")
    assert env["status"] == "ok", env["error"]
    artifact = env["data"]["artifact"]
    assert artifact["passed"] and artifact["probe_status"] == "verified"
    assert artifact["sha256"] == hashlib.sha256(b"synthetic output").hexdigest()
    assert env["data"]["projected_output"]["duration_seconds"] == 2.0
    shas = {p["id"]: p["sha256"] for p in env["provenance"] if p["kind"] == "artifact"}
    assert shas == {
        "source": hashlib.sha256(b"synthetic source").hexdigest(),
        "output": artifact["sha256"],
    }


def test_execute_reports_output_dimension_mismatch(workspace, monkeypatch) -> None:
    _stub_binaries(monkeypatch, available=True)
    (workspace / "in.mp4").write_bytes(b"synthetic source")

    def fake_execute(self, src, dst, nodes):
        Path(dst).write_bytes(b"x")
        return Path(dst)

    monkeypatch.setattr(contracts.FFmpegExecutor, "execute", fake_execute)
    _stub_probe(monkeypatch, lambda path, **kwargs: MediaProbe(4.0, 1920, 1080, 25.0, "h264", None))
    env = _execute(approved=True, prompt="resize to 640x360")
    assert env["status"] == "error"
    assert env["error"]["code"] == "OUTPUT_VERIFICATION_FAILED"


def test_execute_maps_budget_rejection_to_blocked(workspace, monkeypatch) -> None:
    _stub_binaries(monkeypatch, available=True)
    (workspace / "in.mp4").write_bytes(b"synthetic source")
    import multimodal_studio.executor as executor_module

    monkeypatch.setattr(
        executor_module,
        "probe_media",
        lambda *a, **k: MediaProbe(600.0, 3840, 2160, 60.0, "h264", "aac"),
    )
    env = _execute(approved=True, budget={"max_megapixel_frames": 1000})
    assert env["status"] == "blocked"
    assert env["error"]["code"] == "BUDGET_EXCEEDED"
    assert not (workspace / "out.mp4").exists()


def test_verify_artifact_ok_and_hash_mismatch(workspace) -> None:
    (workspace / "clip.bin").write_bytes(b"synthetic artifact")
    digest = hashlib.sha256(b"synthetic artifact").hexdigest()
    env = check(run_operation("verify_artifact", {"path": "clip.bin", "expected_sha256": digest}))
    assert env["status"] == "ok"
    assert env["data"]["sha256"] == digest and env["data"]["checks"]["sha256"] is True
    assert env["provenance"][0]["sha256"] == digest
    assert env["data"]["probe_status"] in {"verified", "unavailable", "failed"}

    mismatch = check(
        run_operation("verify_artifact", {"path": "clip.bin", "expected_sha256": "f" * 64})
    )
    assert mismatch["status"] == "ok"
    assert mismatch["data"]["passed"] is False


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({}, "INVALID_INPUT"),
        ({"path": "clip.bin", "expected_sha256": "xyz"}, "INVALID_INPUT"),
        ({"path": "clip.bin", "expected_width": "64"}, "INVALID_INPUT"),
        ({"path": "clip.bin", "unknown": 1}, "INVALID_INPUT"),
        ({"path": "missing.bin"}, "ARTIFACT_NOT_FOUND"),
    ],
)
def test_verify_artifact_errors(workspace, payload, code) -> None:
    (workspace / "clip.bin").write_bytes(b"x")
    env = check(run_operation("verify_artifact", payload))
    assert env["status"] == "error"
    assert env["error"]["code"] == code


def test_verify_artifact_blocks_paths_outside_workspace(workspace, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside") / "secret.bin"
    outside.write_bytes(b"x")
    env = check(run_operation("verify_artifact", {"path": str(outside)}))
    assert env["status"] == "blocked"
    assert env["error"]["code"] == "PATH_OUTSIDE_WORKSPACE"
