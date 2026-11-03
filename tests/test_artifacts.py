import hashlib
import subprocess
from pathlib import Path

import pytest

import multimodal_studio.artifacts as artifacts_module
from multimodal_studio.artifacts import sha256_file, verify_artifact
from multimodal_studio.executor import MediaProbe

MISSING = "definitely-not-ffprobe-binary"


def _write(tmp_path: Path, data: bytes = b"synthetic artifact bytes") -> Path:
    path = tmp_path / "artifact.mp4"
    path.write_bytes(data)
    return path


def test_sha256_matches_hashlib_for_multichunk_file(tmp_path: Path) -> None:
    data = bytes(range(256)) * 9000  # > 1 MiB, exercises chunking
    path = _write(tmp_path, data)
    assert sha256_file(path) == hashlib.sha256(data).hexdigest()


def test_hash_only_verification_without_ffprobe_reports_unavailable(tmp_path: Path) -> None:
    path = _write(tmp_path)
    result = verify_artifact(path, ffprobe_binary=MISSING)
    assert result.probe_status == "unavailable"
    assert result.media is None
    assert result.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result.passed  # no media expectations were requested


def test_media_expectations_never_pass_without_ffprobe(tmp_path: Path) -> None:
    result = verify_artifact(_write(tmp_path), expected_width=64, ffprobe_binary=MISSING)
    assert result.probe_status == "unavailable"
    assert not result.passed
    assert any("unavailable" in problem for problem in result.problems)


def test_sha256_mismatch_fails(tmp_path: Path) -> None:
    result = verify_artifact(_write(tmp_path), expected_sha256="0" * 64, ffprobe_binary=MISSING)
    assert result.checks["sha256"] is False
    assert not result.passed


def test_empty_artifact_fails(tmp_path: Path) -> None:
    result = verify_artifact(_write(tmp_path, b""), ffprobe_binary=MISSING)
    assert not result.passed


def test_probe_checks_compare_dimensions_and_duration(monkeypatch, tmp_path: Path) -> None:
    probe = MediaProbe(2.0, 64, 48, 12.0, "mpeg4", None)
    monkeypatch.setattr(artifacts_module, "probe_media", lambda *a, **k: probe)
    ok = verify_artifact(
        _write(tmp_path), expected_width=64, expected_height=48,
        expected_duration_seconds=2.05, require_video=True,
    )
    assert ok.probe_status == "verified" and ok.passed
    bad = verify_artifact(
        _write(tmp_path), expected_width=32, expected_duration_seconds=3.0, require_audio=True,
    )
    assert not bad.passed
    assert bad.checks == {"non_empty": True, "width": False, "duration": False, "has_audio": False}


def test_unreadable_media_reports_probe_failure(monkeypatch, tmp_path: Path) -> None:
    def broken(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["ffprobe"])

    monkeypatch.setattr(artifacts_module, "probe_media", broken)
    result = verify_artifact(_write(tmp_path))
    assert result.probe_status == "failed"
    assert not result.passed


def test_missing_artifact_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        verify_artifact(tmp_path / "missing.mp4")
