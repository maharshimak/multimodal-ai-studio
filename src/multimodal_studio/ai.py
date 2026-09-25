from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class AICapability:
    name: str
    available: bool
    backend: str
    purpose: str


def detect_ai_capabilities() -> tuple[AICapability, ...]:
    return (
        AICapability(
            name="speech_transcription",
            available=importlib.util.find_spec("faster_whisper") is not None,
            backend="faster-whisper",
            purpose="Timestamped speech-to-text for captions and transcripts.",
        ),
        AICapability(
            name="diffusion_image_generation",
            available=(
                importlib.util.find_spec("diffusers") is not None
                and importlib.util.find_spec("torch") is not None
            ),
            backend="diffusers",
            purpose="Local Hugging Face diffusion pipelines for image generation.",
        ),
    )


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str


def _srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        raise ValueError("timestamp cannot be negative")
    total_ms = round(seconds * 1000)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def segments_to_srt(segments: list[TranscriptSegment]) -> str:
    blocks: list[str] = []
    for index, segment in enumerate(segments, start=1):
        if segment.end_seconds < segment.start_seconds or not segment.text.strip():
            raise ValueError("invalid transcript segment")
        blocks.append(
            "\n".join(
                [
                    str(index),
                    (
                        f"{_srt_timestamp(segment.start_seconds)} --> "
                        f"{_srt_timestamp(segment.end_seconds)}"
                    ),
                    segment.text.strip(),
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


class WhisperTranscriber:
    """Real local speech recognition via faster-whisper, loaded lazily."""

    def __init__(
        self,
        model_size: str = "base",
        *,
        device: str = "auto",
        compute_type: str = "default",
    ) -> None:
        if not model_size.strip():
            raise ValueError("model_size is required")
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model: Any | None = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError(
                "faster-whisper is not installed; install the AI transcription extra."
            ) from error
        self._model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
        )
        return self._model

    def transcribe(
        self,
        source: str | Path,
        *,
        language: str | None = None,
    ) -> tuple[list[TranscriptSegment], str]:
        path = Path(source)
        if not path.is_file():
            raise FileNotFoundError(path)
        model = self._load()
        generated, info = model.transcribe(str(path), language=language)
        segments = [
            TranscriptSegment(
                start_seconds=float(segment.start),
                end_seconds=float(segment.end),
                text=str(segment.text),
            )
            for segment in generated
            if str(segment.text).strip()
        ]
        detected_language = str(getattr(info, "language", language or "unknown"))
        return segments, detected_language


class DiffusersImageGenerator:
    """Optional local diffusion backend; no model is downloaded until explicitly used."""

    def __init__(
        self,
        model_id: str,
        *,
        device: str = "cpu",
        torch_dtype: Any | None = None,
    ) -> None:
        if not model_id.strip():
            raise ValueError("model_id is required")
        self.model_id = model_id
        self.device = device
        self.torch_dtype = torch_dtype
        self._pipeline: Any | None = None

    def _load(self):
        if self._pipeline is not None:
            return self._pipeline
        try:
            from diffusers import DiffusionPipeline
        except ImportError as error:
            raise RuntimeError(
                "diffusers is not installed; install the AI generation extra."
            ) from error
        kwargs: dict[str, Any] = {}
        if self.torch_dtype is not None:
            kwargs["torch_dtype"] = self.torch_dtype
        pipeline = DiffusionPipeline.from_pretrained(self.model_id, **kwargs)
        self._pipeline = pipeline.to(self.device)
        return self._pipeline

    def generate(
        self,
        prompt: str,
        destination: str | Path,
        *,
        negative_prompt: str | None = None,
        num_inference_steps: int = 30,
    ) -> Path:
        if not prompt.strip():
            raise ValueError("prompt must be non-empty")
        if not 1 <= num_inference_steps <= 200:
            raise ValueError("num_inference_steps must be between 1 and 200")
        pipeline = self._load()
        result = pipeline(
            prompt=prompt,
            negative_prompt=negative_prompt,
            num_inference_steps=num_inference_steps,
        )
        images = getattr(result, "images", None)
        if not images:
            raise RuntimeError("diffusion pipeline returned no images")
        output = Path(destination)
        output.parent.mkdir(parents=True, exist_ok=True)
        images[0].save(output)
        return output
