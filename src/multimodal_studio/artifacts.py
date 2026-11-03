"""Artifact metadata and output verification.

Every artifact gets a real SHA-256 of its bytes. Media-level checks (dimensions,
duration, streams) use ``ffprobe`` when it is installed; when it is not, the
verification reports ``probe_status="unavailable"`` instead of claiming success.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from multimodal_studio.executor import FFmpegUnavailableError, MediaExecutionError, probe_media

ProbeStatus = Literal["verified", "unavailable", "failed"]

_CHUNK = 1024 * 1024


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ArtifactVerification:
    path: str
    size_bytes: int
    sha256: str
    probe_status: ProbeStatus
    media: dict[str, object] | None
    checks: dict[str, bool] = field(default_factory=dict)
    problems: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        """True only if every requested check ran and passed.

        A check that needs ffprobe while ffprobe is unavailable counts as not passed.
        """
        return not self.problems and all(self.checks.values())

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["problems"] = list(self.problems)
        data["passed"] = self.passed
        return data


def verify_artifact(
    path: str | Path,
    *,
    expected_sha256: str | None = None,
    expected_width: int | None = None,
    expected_height: int | None = None,
    expected_duration_seconds: float | None = None,
    duration_tolerance_seconds: float = 0.1,
    require_video: bool = False,
    require_audio: bool = False,
    ffprobe_binary: str = "ffprobe",
    max_source_bytes: int = 2_000_000_000,
) -> ArtifactVerification:
    """Hash an artifact and, when ffprobe is available, check its media properties."""
    artifact = Path(path)
    if not artifact.is_file():
        raise FileNotFoundError(artifact)
    if duration_tolerance_seconds < 0:
        raise ValueError("duration_tolerance_seconds must be non-negative")
    size = artifact.stat().st_size
    digest = sha256_file(artifact)
    checks: dict[str, bool] = {"non_empty": size > 0}
    problems: list[str] = []
    if size == 0:
        problems.append("artifact is empty")
    if expected_sha256 is not None:
        checks["sha256"] = digest == expected_sha256.lower()
        if not checks["sha256"]:
            problems.append("sha256 does not match the expected digest")

    wants_probe = any(
        value is not None for value in (expected_width, expected_height, expected_duration_seconds)
    ) or require_video or require_audio

    media: dict[str, object] | None = None
    probe_status: ProbeStatus
    try:
        probe = probe_media(
            artifact, ffprobe_binary=ffprobe_binary, max_source_bytes=max_source_bytes
        )
    except FFmpegUnavailableError:
        probe_status = "unavailable"
        if wants_probe:
            problems.append(f"{ffprobe_binary} is unavailable; media checks were not run")
    except (MediaExecutionError, subprocess.SubprocessError, ValueError, OSError) as error:
        probe_status = "failed"
        problems.append(f"ffprobe could not read the artifact: {type(error).__name__}")
    else:
        probe_status = "verified"
        media = asdict(probe)
        if expected_width is not None:
            checks["width"] = probe.width == expected_width
        if expected_height is not None:
            checks["height"] = probe.height == expected_height
        if expected_duration_seconds is not None:
            checks["duration"] = (
                probe.duration_seconds is not None
                and abs(probe.duration_seconds - expected_duration_seconds)
                <= duration_tolerance_seconds
            )
        if require_video:
            checks["has_video"] = probe.video_codec is not None
        if require_audio:
            checks["has_audio"] = probe.audio_codec is not None
        problems.extend(f"{name} check failed" for name, ok in checks.items() if not ok
                        and name not in {"non_empty", "sha256"})

    return ArtifactVerification(
        path=str(artifact),
        size_bytes=size,
        sha256=digest,
        probe_status=probe_status,
        media=media,
        checks=checks,
        problems=tuple(problems),
    )
