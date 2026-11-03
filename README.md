# Multimodal AI Studio

**A MAK'MA Studio Product · MAK'MA Labs**

[Live Product Demo](https://maharshimak.github.io/makma-ai-os/projects/multimodal-ai-studio/) · [MAK'MA Labs](https://maharshimak.github.io/makma-ai-os/projects/)

Media automation and AI inference toolkit combining validated prompt-to-edit planning, shell-free FFmpeg execution and optional real local transcription/image-generation backends.


## Product contract — engineering upgrade

**Problem and audience:** A media workflow preflight planner for editors estimating processing work before expensive rendering.

**Live tool:** https://maharshimak.github.io/makma-ai-os/projects/multimodal-ai-studio/

**Implemented browser workflow:** Source/output resolution, FPS, duration, speed and budget drive ordered operation workload, output frames, utilization, warnings and an exportable fingerprinted plan. Empty plans block. Background replacement discloses asset/compositor requirements; subtitles disclose transcription requirements.

**Backend and parity contract:** Python offers deterministic operation planning, stage validation and render budget enforcement. Empty plans now fail closed; unsupported operation/stage pairs are rejected. Browser workload v2 uses output resolution and retimed frame counts; the Python legacy estimate uses source frames. These estimates are different documented modes.

**Architecture:** `makma-ai-os/demo` is the shared web product source and Pages deployment. This repository owns its Python domain package. The central `tests/e2e` suite exercises all nine products; `tests/fixtures/python-parity.json` plus `scripts/generate_parity.py` guard shared mathematical contracts. Backend revisions used for regeneration are pinned in the central `backend-lock.json`.

**Safety and limitations:** The Python package has a real shell-free FFmpeg executor plus optional `faster-whisper` transcription and Hugging Face Diffusers image generation adapters. These AI backends are lazy and unavailable unless their explicit extras and model weights are installed; the public browser page remains a deterministic preflight planner and does not pretend to run those models. Background segmentation/compositing, video generation, browser uploads, GPU-time/VRAM prediction and asynchronous render jobs remain future work. Workload weights are planning heuristics, not measured GPU benchmarks.

**Verification:** Run `python -m ruff check .` and `python -m pytest -q`. `tests/test_engineering_upgrade.py` protects the new rejection/correctness paths. Central web checks: `npm ci`, `npm test`, `npm run build`, `npx playwright install --with-deps chromium`, `npm run test:e2e`. CI gates publishing on browser interactions and validates all public URLs after deployment.

**Executable local core:** The FFmpeg adapter now supports typed trim, crop, resize, volume, retime, cinematic grade and audio-denoise nodes with validated bounds and no shell invocation. AI-only operations such as automatic subtitles and background segmentation still fail explicitly unless a real adapter is configured.

**Highest-value next work:** Measured hardware profiles, real compositor/transcription adapters and render job cancellation.

**Provenance:** Independent MAK’MA Studio engineering implementation; examples are synthetic and no employer code or data is included. Existing MIT license applies.


## Implemented now

- Prompt planning for retiming, color grading, audio denoising, subtitles and background segmentation, plus typed parsing for explicit trim ranges, resize/crop dimensions, volume gain and playback speed.
- Typed edit graph: every operation has a fixed stage and canonical position, and parameters are checked against a per-operation schema (unknown keys, missing required keys, non-integer pixel values, booleans, NaN/inf and out-of-range values are rejected with `PlanValidationError`). `trim` always runs before `retime` and `crop` before `resize`, so trim bounds and crop offsets refer to the source.
- Exact frame/duration arithmetic (`timeline.py`): rational frame rates such as `30000/1001`, explicit `nearest`/`floor`/`ceil` frame counting, and projection of a plan onto source metadata (output resolution, duration and frame count). Plans that cannot apply to the source, such as a trim starting after the end or a crop window outside the frame, are rejected with `MediaPlanError` before rendering.
- Output budget checks for projected duration and resolution, in addition to the existing workload budget.
- Artifact verification: SHA-256 of the output plus `ffprobe` checks of dimensions, duration and streams when `ffprobe` is installed; otherwise the result reports `probe_status="unavailable"` rather than success.
- Ordered operation stages and duplicate-operation validation.
- Independent mutable parameters for each plan and JSON export.
- Real `ffprobe` metadata inspection for local media files.
- Shell-free FFmpeg command construction and execution for supported trim, crop, resize, volume, retime, cinematic color-grade and audio-denoise operations.
- Explicit failure (`UnsupportedOperationError`, `FFmpegUnavailableError`) when an operation has no configured real executor or the binaries are missing, instead of pretending a render succeeded.
- Optional `WhisperTranscriber` with timestamped transcript segments and SRT rendering (`.[transcription]`).
- Optional `DiffusersImageGenerator` for local Hugging Face diffusion pipelines (`.[generation]`).
- Runtime capability detection reports whether optional AI backends are actually installed.
- Optional `WhisperTranscriber` powered by `faster-whisper`, producing timestamped transcript segments and SRT artifacts.
- Optional `DiffusersImageGenerator` for local Hugging Face diffusion pipelines; models are loaded only when explicitly invoked.
- Capability detection reports whether optional AI runtimes are actually installed.

## makma.v1 operations

`multimodal_studio.contracts` implements the shared MAK'MA `makma.v1` envelope (`contracts/makma.v1.schema.json`). Use `capabilities()` to list operations and `run_operation(operation, payload, run_id=None, correlation_id=None)` to run one in-process. All operations report `execution_mode: "deterministic_offline"`: planning is keyword/regex based and rendering uses the local FFmpeg binary; no model inference is involved.

| Operation | Side effects | Input | `data` on success |
| --- | --- | --- | --- |
| `plan` | none | `prompt` or `nodes`; optional `media` (`width`, `height`, `duration_seconds`, `fps` as number or `"30000/1001"`) and `budget` | canonical `nodes`, `fingerprint` (SHA-256 of canonical JSON), `executable`, `unsupported_operations`, `ffmpeg_filters`, and with `media`: workload `estimate` and projected `output` |
| `execute` | writes `destination_path`; requires approval | `source_path`, `destination_path`, `prompt` or `nodes`, `approved`, optional `timeout_seconds` (1-3600) and `budget` | `output_path`, `projected_output`, `artifact` verification (SHA-256, probe result); provenance carries source and output SHA-256 |
| `verify_artifact` | none | `path`; optional `expected_sha256`, `expected_width`, `expected_height`, `expected_duration_seconds`, `duration_tolerance_seconds`, `require_video`, `require_audio` | size, SHA-256, `probe_status` (`verified`, `unavailable` or `failed`), probed media fields, per-check results, `passed` |

Error codes: `UNKNOWN_OPERATION`, `INVALID_INPUT`, `PLAN_INVALID`, `PLAN_EMPTY`, `PLAN_INCOMPATIBLE_WITH_MEDIA`, `UNSUPPORTED_OPERATION`, `FFMPEG_UNAVAILABLE`, `SOURCE_NOT_FOUND`, `ARTIFACT_NOT_FOUND`, `EXECUTION_FAILED`, `EXECUTION_TIMEOUT`, `OUTPUT_VERIFICATION_FAILED`. Budget violations (`BUDGET_EXCEEDED`) and paths outside the workspace (`PATH_OUTSIDE_WORKSPACE`) return status `blocked` with a `deny` policy. `execute` without `approved: true` returns `pending_approval` and does not render.

Paths for `execute` and `verify_artifact` are resolved against the workspace root given by the `MULTIMODAL_STUDIO_WORKSPACE` environment variable (default: the current working directory).

## Scope and limitations

The deterministic planner is still keyword-based, so negation and complex mixed intents are not fully understood. The Python executor can inspect local media and perform a bounded subset of real FFmpeg edits. Optional transcription and image generation are available through separate installed backends, but browser uploads, timeline composition, segmentation/compositing, generative video, background jobs, a job state machine and cancellation of running renders are not yet implemented. Projected output frame counts assume the source frame rate is kept. Unsupported operations fail explicitly rather than being simulated. No standalone API or UI is included in this satellite repository; the public browser experience is owned by `makma-ai-os`.

## Installation and development

Requires Python 3.12 or newer. Run from this project directory.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest -q
python -m pip wheel --no-deps . -w dist
```

On Windows, activate with `.venv\Scripts\Activate.ps1`.

## Library usage

```python
from multimodal_studio.planner import plan, to_json
print(to_json(plan("cinematic slow motion, remove background noise, subtitles")))
```

## Configuration

Configuration is supplied through Python function/constructor arguments. No credentials or environment file are needed for the offline example. The only environment variable is `MULTIMODAL_STUDIO_WORKSPACE`, which bounds the file paths accepted by the `makma.v1` `execute` and `verify_artifact` operations.

## Container

```bash
docker build -t multimodal-ai-studio .
docker run --rm multimodal-ai-studio
```

## Repository structure

| Path | Purpose |
| --- | --- |
| `src/multimodal_studio/` | Implementation |
| `contracts/makma.v1.schema.json` | Shared MAK'MA envelope schema (vendored, byte-identical across repos) |
| `tests/` | Offline unit and regression tests; `tests/test_real_ffmpeg_contract.py` runs only where `ffmpeg`/`ffprobe` are installed |
| `docs/DESIGN.md` | Architecture and trust boundaries |
| `.github/workflows/ci.yml` | Install, lint, tests, wheel and container build |
| `pyproject.toml` | Dependencies and package configuration |

## Next engineering work

Asynchronous render jobs with an explicit state machine and cancellation; transcription/subtitle adapters; segmentation/compositor adapters; ComfyUI/local-model integration; timeline UI. These are planned work, not current capabilities.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). CI runs on every push and pull request through `.github/workflows/ci.yml`.

## License and provenance

[MIT](LICENSE), copyright 2026 Maharshi Patel. This public portfolio implementation is independent of employer systems and contains no confidential employer code or data. Examples and test fixtures are synthetic.
