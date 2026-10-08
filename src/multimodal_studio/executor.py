from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from multimodal_studio.budget import MediaProfile, RenderBudget, enforce_render_budget
from multimodal_studio.planner import EditNode, validate


class MediaExecutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MediaProbe:
    duration_seconds: float | None
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None


def _require_binary(name: str) -> str:
    resolved = shutil.which(name)
    if resolved is None:
        raise MediaExecutionError(f"{name} is not installed or is not on PATH.")
    return resolved


def _parse_frame_rate(value: object) -> float | None:
    if value in (None, "", "0/0"):
        return None
    text = str(value)
    try:
        if "/" in text:
            numerator, denominator = text.split("/", 1)
            denominator_value = float(denominator)
            if denominator_value == 0:
                return None
            rate = float(numerator) / denominator_value
        else:
            rate = float(text)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


def probe_media(
    path: str | Path,
    *,
    ffprobe_binary: str = "ffprobe",
    max_source_bytes: int = 2_000_000_000,
) -> MediaProbe:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.stat().st_size > max_source_bytes:
        raise MediaExecutionError(
            f"Source media exceeds the {max_source_bytes} byte processing limit."
        )
    ffprobe = _require_binary(ffprobe_binary)
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
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
        fps=_parse_frame_rate(video.get("r_frame_rate")),
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
        if node.operation == "trim":
            start = float(node.parameters.get("start_seconds", 0.0))
            end = float(node.parameters.get("end_seconds", 0.0))
            if start < 0 or end <= start or end - start > 4 * 60 * 60:
                raise ValueError("Trim requires 0 <= start < end with at most four hours.")
            video_filters.append(f"trim=start={start:g}:end={end:g},setpts=PTS-STARTPTS")
            audio_filters.append(f"atrim=start={start:g}:end={end:g},asetpts=PTS-STARTPTS")
        elif node.operation == "resize":
            width = int(node.parameters.get("width", 0))
            height = int(node.parameters.get("height", 0))
            if not 16 <= width <= 7680 or not 16 <= height <= 4320:
                raise ValueError("Resize dimensions must be between 16x16 and 7680x4320.")
            video_filters.append(f"scale={width}:{height}:flags=lanczos")
        elif node.operation == "crop":
            width = int(node.parameters.get("width", 0))
            height = int(node.parameters.get("height", 0))
            x = int(node.parameters.get("x", 0))
            y = int(node.parameters.get("y", 0))
            if width <= 0 or height <= 0 or x < 0 or y < 0:
                raise ValueError("Crop requires positive dimensions and non-negative offsets.")
            video_filters.append(f"crop={width}:{height}:{x}:{y}")
        elif node.operation == "volume":
            gain_db = float(node.parameters.get("gain_db", 0.0))
            if not -60.0 <= gain_db <= 24.0:
                raise ValueError("Volume gain must be between -60 dB and +24 dB.")
            audio_filters.append(f"volume={gain_db:g}dB")
        elif node.operation == "retime":
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
    """Executes supported edit graphs with preflight workload enforcement."""

    def __init__(
        self,
        *,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        timeout_seconds: float = 1800.0,
        max_source_bytes: int = 2_000_000_000,
        render_budget: RenderBudget | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if isinstance(max_source_bytes, bool) or not isinstance(max_source_bytes, int):
            raise TypeError("max_source_bytes must be an integer")
        if max_source_bytes <= 0:
            raise ValueError("max_source_bytes must be positive")
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary
        self.timeout_seconds = timeout_seconds
        self.max_source_bytes = max_source_bytes
        self.render_budget = render_budget or RenderBudget()

    def _preflight(self, source: Path, nodes: list[EditNode]) -> MediaProbe:
        probe = probe_media(
            source,
            ffprobe_binary=self.ffprobe_binary,
            max_source_bytes=self.max_source_bytes,
        )
        if (
            probe.width is None
            or probe.height is None
            or probe.duration_seconds is None
            or probe.fps is None
        ):
            raise MediaExecutionError(
                "Source media is missing width, height, duration, or frame-rate metadata."
            )
        enforce_render_budget(
            nodes,
            MediaProfile(
                width=probe.width,
                height=probe.height,
                duration_seconds=probe.duration_seconds,
                fps=probe.fps,
            ),
            self.render_budget,
        )
        return probe

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
        if source_path.stat().st_size > self.max_source_bytes:
            raise MediaExecutionError(
                f"Source media exceeds the {self.max_source_bytes} byte processing limit."
            )

        self._preflight(source_path, nodes)
        ffmpeg = _require_binary(self.ffmpeg_binary)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a private file with the same media extension and publish only
        # after FFmpeg exits successfully. Failed jobs never expose partial output.
        with tempfile.NamedTemporaryFile(
            prefix=".render-", suffix=destination_path.suffix or ".mp4",
            dir=destination_path.parent, delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        try:
            command = build_ffmpeg_command(
                source_path,
                temporary_path,
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
            except subprocess.TimeoutExpired as error:
                raise MediaExecutionError("FFmpeg render timed out.") from error
            except subprocess.CalledProcessError as error:
                detail = (error.stderr or "").strip()[-1000:]
                raise MediaExecutionError(f"FFmpeg failed: {detail}") from error
            if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
                raise MediaExecutionError("FFmpeg produced no output media.")
            os.replace(temporary_path, destination_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        return destination_path
