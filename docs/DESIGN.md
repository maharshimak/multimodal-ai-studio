# Design and operating boundaries

Prompt-to-edit planner and bounded local FFmpeg execution engine.

## Scope

The library turns supported phrases (or an explicit typed edit graph) into an ordered list of media operations, checks that plan against source metadata and a render budget, and can render the supported subset with a local `ffmpeg` binary. Intent detection uses keywords and regular expressions; negation and complex mixed intents are not understood. Segmentation, automatic subtitles, compositing and generative video are not executed: such operations fail with `UnsupportedOperationError`. No HTTP API or UI is included.

## Pipeline

1. **Plan** (`planner.py`). Every operation has a fixed stage and a fixed position (`OPERATION_ORDER`). `canonical_order` sorts any graph into that order, so filter order never depends on input order. Within the temporal stage `trim` precedes `retime`, so trim bounds always refer to the source timeline; within the vision stage `crop` precedes `resize`, so crop offsets refer to source pixels. `validate` checks each node against `PARAMETER_SCHEMA`: known parameters only, required parameters present, strict types (booleans are not numbers, fractional pixel values are rejected, NaN/inf are rejected) and ranges. Failures raise `PlanValidationError`, a `ValueError` subclass.
2. **Project** (`timeline.py`). Frame rates are parsed into exact `Fraction`s (`30000/1001` stays exact). `frame_count` has explicit `nearest` (halves round up), `floor` and `ceil` modes. `project_output` applies the plan to source width/height/duration/fps and returns the output resolution, duration and frame count, or raises `MediaPlanError` when the plan cannot apply (trim starting at/after the source end, crop window outside the frame). A trim end past the source end is clamped, matching FFmpeg's `trim` filter.
3. **Budget** (`budget.py`). `enforce_render_budget` keeps the existing source-frame workload heuristic (operation weights are planning heuristics, not measurements). `enforce_output_budget` additionally limits projected output duration (`max_output_seconds`, default 4 h) and resolution (`max_output_pixels`, default 7680x4320).
4. **Execute** (`executor.py`). `FFmpegExecutor` probes the source with `ffprobe`, runs both budget checks and the projection, then invokes `ffmpeg` with an argument list (never a shell). Missing binaries raise `FFmpegUnavailableError`.
5. **Verify** (`artifacts.py`). `verify_artifact` computes a SHA-256 of the file and, if `ffprobe` is available, checks dimensions, duration (with a tolerance) and stream presence. When `ffprobe` is missing the result says `probe_status="unavailable"` and any requested media check counts as not passed.

## makma.v1 boundary

`contracts.py` exposes `capabilities()` and `run_operation()`. File paths given to `execute` and `verify_artifact` are resolved against a workspace root (`MULTIMODAL_STUDIO_WORKSPACE`, default: the current working directory); paths that resolve outside it are refused with status `blocked`. `execute` is declared `requires_approval`; without `approved: true` it returns `pending_approval` and does not render.

## Validation

Tests use synthetic fixtures only. Tests that need real `ffmpeg`/`ffprobe` are skipped where those binaries are absent; everything else runs offline. Tests do not certify model quality or rendering quality.

## Planned evolution

Explicit job state machine and cancellation of running renders; measured hardware profiles; segmentation/compositor and subtitle adapters; timeline UI.
