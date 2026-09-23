from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from multimodal_studio.planner import EditNode, validate


class MediaExecutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MediaProbe:
    duration_seconds: float | None
    width: int | None
    height: int | None
    video_codec: str | None
    audio_codec: str | None


def _require_binary(name: str) -> str:
    resolved = shutil.which(name)
    if resolved is None:
        raise MediaExecutionError(f"{name} is not installed or is not on PATH.")
    return resolved


def probe_media(path: str | Path, *, ffprobe_binary: str = "ffprobe") -> MediaProbe:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    ffprobe = _require_binary(ffprobe_binary)
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height",
            "-of",
            "json",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    data = json.loads(completed.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    raw_duration = data.get("format", {}).get("duration")
    return MediaProbe(
        duration_seconds=float(raw_duration) if raw_duration is not None else None,
        width=int(video["width"]) if video.get("width") is not None else None,
        height=int(video["height"]) if video.get("height") is not None else None,
        video_codec=video.get("codec_name"),
        audio_codec=audio.get("codec_name"),
    )


def build_ffmpeg_command(
    source: str | Path,
    destination: str | Path,
    nodes: list[EditNode],
    *,
    ffmpeg_binary: str = "ffmpeg",
) -> list[str]:
    validate(nodes)
    source_path = Path(source)
    destination_path = Path(destination)
    if source_path == destination_path:
        raise ValueError("Source and destination must be different files.")

    video_filters: list[str] = []
    audio_filters: list[str] = []
    unsupported: list[str] = []

    for node in nodes:
        if node.operation == "retime":
            speed = float(node.parameters.get("speed", 1.0))
            if not 0.5 <= speed <= 2.0:
                raise ValueError("FFmpeg retime speed must be between 0.5x and 2.0x.")
            video_filters.append(f"setpts=PTS/{speed:g}")
            audio_filters.append(f"atempo={speed:g}")
        elif node.operation == "color_grade":
            preset = str(node.parameters.get("preset", ""))
            if preset != "cinematic-teal":
                raise ValueError(f"Unsupported color-grade preset: {preset}")
            video_filters.append("eq=contrast=1.08:saturation=1.12")
            video_filters.append("colorbalance=bs=.06:gs=.02:rs=-.03")
        elif node.operation == "audio_denoise":
            strength = float(node.parameters.get("strength", 0.7))
            if not 0.0 <= strength <= 1.0:
                raise ValueError("Denoise strength must be between 0 and 1.")
            noise_floor = -35 - (strength * 20)
            audio_filters.append(f"afftdn=nf={noise_floor:.1f}")
        else:
            unsupported.append(node.operation)

    if unsupported:
        raise MediaExecutionError(
            "No local executor is configured for: " + ", ".join(sorted(unsupported))
        )

    command = [ffmpeg_binary, "-y", "-i", str(source_path)]
    if video_filters:
        command.extend(["-vf", ",".join(video_filters)])
    if audio_filters:
        command.extend(["-af", ",".join(audio_filters)])
    command.extend(["-movflags", "+faststart", str(destination_path)])
    return command


class FFmpegExecutor:
    """Executes supported edit graphs without invoking a shell."""

    def __init__(self, *, ffmpeg_binary: str = "ffmpeg", timeout_seconds: float = 1800.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.ffmpeg_binary = ffmpeg_binary
        self.timeout_seconds = timeout_seconds

    def execute(
        self,
        source: str | Path,
        destination: str | Path,
        nodes: list[EditNode],
    ) -> Path:
        source_path = Path(source)
        destination_path = Path(destination)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        ffmpeg = _require_binary(self.ffmpeg_binary)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        command = build_ffmpeg_command(
            source_path,
            destination_path,
            nodes,
            ffmpeg_binary=ffmpeg,
        )
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or "").strip()[-1000:]
            raise MediaExecutionError(f"FFmpeg failed: {detail}") from error
        return destination_path
