import subprocess
from pathlib import Path

import pytest

import multimodal_studio.executor as module
from multimodal_studio.executor import FFmpegExecutor, MediaExecutionError


@pytest.fixture
def ready_executor(monkeypatch):
    executor = FFmpegExecutor()
    monkeypatch.setattr(executor, "_preflight", lambda source, nodes: None)
    monkeypatch.setattr(module, "_require_binary", lambda name: name)
    return executor


def test_atomic_render_only_publishes_completed_media(monkeypatch, tmp_path: Path, ready_executor):
    source = tmp_path / "source.mp4"
    target = tmp_path / "out.mp4"
    source.write_bytes(b"input")
    target.write_bytes(b"previous")

    def complete(command, **kwargs):
        Path(command[-1]).write_bytes(b"completed")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", complete)
    assert ready_executor.execute(source, target, []) == target
    assert target.read_bytes() == b"completed"
    assert list(tmp_path.glob(".render-*")) == []


@pytest.mark.parametrize("failure", ["timeout", "exit"])
def test_failed_render_keeps_existing_output_and_removes_temporary_file(
    monkeypatch, tmp_path: Path, ready_executor, failure
):
    source = tmp_path / "source.mp4"
    target = tmp_path / "out.mp4"
    source.write_bytes(b"input")
    target.write_bytes(b"previous")

    def fail(command, **kwargs):
        Path(command[-1]).write_bytes(b"partial")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1)
        raise subprocess.CalledProcessError(1, command, stderr="render failed")

    monkeypatch.setattr(module.subprocess, "run", fail)
    with pytest.raises(MediaExecutionError):
        ready_executor.execute(source, target, [])
    assert target.read_bytes() == b"previous"
    assert list(tmp_path.glob(".render-*")) == []


def test_successful_ffmpeg_exit_without_media_never_publishes(monkeypatch, tmp_path: Path, ready_executor):
    source = tmp_path / "source.mp4"
    target = tmp_path / "out.mp4"
    source.write_bytes(b"input")
    target.write_bytes(b"previous")

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0),
    )
    with pytest.raises(MediaExecutionError, match="no output media"):
        ready_executor.execute(source, target, [])
    assert target.read_bytes() == b"previous"
    assert list(tmp_path.glob(".render-*")) == []


def test_atomic_publish_failure_preserves_old_target(monkeypatch, tmp_path: Path, ready_executor):
    source = tmp_path / "source.mp4"
    target = tmp_path / "out.mp4"
    source.write_bytes(b"input")
    target.write_bytes(b"previous")

    def complete(command, **kwargs):
        Path(command[-1]).write_bytes(b"rendered")
        return subprocess.CompletedProcess(command, 0)

    def cannot_publish(source, destination):
        raise OSError("simulated atomic replacement failure")

    monkeypatch.setattr(module.subprocess, "run", complete)
    monkeypatch.setattr(module.os, "replace", cannot_publish)
    with pytest.raises(OSError, match="atomic replacement failure"):
        ready_executor.execute(source, target, [])
    assert target.read_bytes() == b"previous"
    assert list(tmp_path.glob(".render-*")) == []
