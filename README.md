# Multimodal AI Studio

Prompt-to-edit planning prototype that converts supported phrases into ordered media-operation specifications.

## Implemented now

- Keyword-based planning for retiming, color grading, audio denoising, subtitles and background segmentation.
- Ordered operation stages and duplicate-operation validation.
- Independent mutable parameters for each plan and JSON export.

## Scope and limitations

This library generates plans only. It does not upload, decode, edit or generate media, run segmentation models, produce subtitles, or render a timeline. Intent detection uses keywords; negation and complex mixed intents are not understood. Validation detects duplicates, not complete parameter or media compatibility. No API, UI or external services are included.

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

Typed parameter validation; media metadata ingestion; preview executor with FFmpeg; model adapters; timeline UI. These are planned work, not current capabilities.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). The standalone CI workflow runs after migration; while nested in the profile repository, the parent CI validates this project.

## License and provenance

[MIT](LICENSE), copyright 2026 Maharshi Patel. This public portfolio implementation is independent of employer systems and contains no confidential employer code or data. Examples and test fixtures are synthetic.
