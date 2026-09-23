# Multimodal AI Studio

**A MAK'MA Studio Product · MAK'MA Labs**

[Live Product Demo](https://maharshimak.github.io/makma-ai-os/projects/multimodal-ai-studio/) · [MAK'MA Labs](https://maharshimak.github.io/makma-ai-os/projects/)

Prompt-to-edit planning prototype that converts supported phrases into ordered media-operation specifications.


## Product contract — engineering upgrade

**Problem and audience:** A media workflow preflight planner for editors estimating processing work before expensive rendering.

**Live tool:** https://maharshimak.github.io/makma-ai-os/projects/multimodal-ai-studio/

**Implemented browser workflow:** Source/output resolution, FPS, duration, speed and budget drive ordered operation workload, output frames, utilization, warnings and an exportable fingerprinted plan. Empty plans block. Background replacement discloses asset/compositor requirements; subtitles disclose transcription requirements.

**Backend and parity contract:** Python offers deterministic operation planning, stage validation and render budget enforcement. Empty plans now fail closed; unsupported operation/stage pairs are rejected. Browser workload v2 uses output resolution and retimed frame counts; the Python legacy estimate uses source frames. These estimates are different documented modes.

**Architecture:** `makma-ai-os/demo` is the shared web product source and Pages deployment. This repository owns its Python domain package. The central `tests/e2e` suite exercises all nine products; `tests/fixtures/python-parity.json` plus `scripts/generate_parity.py` guard shared mathematical contracts. Backend revisions used for regeneration are pinned in the central `backend-lock.json`.

**Safety and limitations:** The Python package now has a real shell-free FFmpeg executor for supported retiming, cinematic color-grade and audio-denoise operations plus ffprobe metadata inspection. Background segmentation, automatic subtitles/transcription, generative media, browser uploads, GPU-time/VRAM prediction and asynchronous render jobs are not implemented. Workload weights remain planning heuristics, not benchmark measurements. Inputs are validated, rendered user values are escaped, and deterministic results are not presented as model inference.

**Verification:** Run `python -m ruff check .` and `python -m pytest -q`. `tests/test_engineering_upgrade.py` protects the new rejection/correctness paths. Central web checks: `npm ci`, `npm test`, `npm run build`, `npx playwright install --with-deps chromium`, `npm run test:e2e`. CI gates publishing on browser interactions and validates all public URLs after deployment.

**Executable local core:** The FFmpeg adapter now supports typed trim, crop, resize, volume, retime, cinematic grade and audio-denoise nodes with validated bounds and no shell invocation. AI-only operations such as automatic subtitles and background segmentation still fail explicitly unless a real adapter is configured.

**Highest-value next work:** Measured hardware profiles, typed operation parameters, real compositor/transcription adapters and render job cancellation.

**Provenance:** Independent MAK’MA Studio engineering implementation; examples are synthetic and no employer code or data is included. Existing MIT license applies.


## Implemented now

- Prompt planning for retiming, color grading, audio denoising, subtitles and background segmentation, plus typed parsing for explicit trim ranges, resize/crop dimensions, volume gain and playback speed.
- Ordered operation stages and duplicate-operation validation.
- Independent mutable parameters for each plan and JSON export.
- Real `ffprobe` metadata inspection for local media files.
- Shell-free FFmpeg command construction and execution for supported retime, cinematic color-grade and audio-denoise operations.
- Explicit failure when an operation has no configured real executor instead of pretending a render succeeded.

## Scope and limitations

The planner is still keyword-based, so negation and complex mixed intents are not fully understood. The Python executor can inspect local media and perform a bounded subset of real FFmpeg edits, but it does not yet provide browser uploads, timeline composition, segmentation models, transcription/subtitle generation, generative image/video execution, background jobs or cancellation. Unsupported operations fail explicitly rather than being simulated. No standalone API or UI is included in this satellite repository; the public browser experience is owned by `makma-ai-os`.

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

Configuration is supplied through Python function/constructor arguments. No credentials or environment file are needed for the offline example.

## Container

```bash
docker build -t multimodal-ai-studio .
docker run --rm multimodal-ai-studio
```

## Repository structure

| Path | Purpose |
| --- | --- |
| `src/multimodal_studio/` | Implementation |
| `tests/` | Offline unit and regression tests |
| `docs/DESIGN.md` | Architecture and trust boundaries |
| `.github/workflows/ci.yml` | Install, lint, tests, wheel and container build |
| `pyproject.toml` | Dependencies and package configuration |

## Next engineering work

Typed parameter validation across every operation; asynchronous render jobs and cancellation; transcription/subtitle adapters; segmentation/compositor adapters; ComfyUI/local-model integration; timeline UI. These are planned work, not current capabilities.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). CI runs on every push and pull request through `.github/workflows/ci.yml`.

## License and provenance

[MIT](LICENSE), copyright 2026 Maharshi Patel. This public portfolio implementation is independent of employer systems and contains no confidential employer code or data. Examples and test fixtures are synthetic.
