# Production engineering

`multimodal_studio.quality` adds deterministic plan fingerprints and structural validation for edit graphs produced from natural-language instructions.

## Why this matters

An edit request should be reproducible and reviewable before expensive media processing begins. The quality layer rejects duplicate operations, unknown stages, non-JSON-safe parameters, out-of-order pipeline stages and oversized plans. A SHA-256 fingerprint identifies the canonical operation graph for caching, audit trails and reproducibility.

## Operational practice

- Persist the plan fingerprint beside rendered assets.
- Validate the graph before dispatching GPU/media workers.
- Bound operation count per request.
- Keep rendering backends isolated from planning and validation.
- Run tests and container builds for every workflow change.
