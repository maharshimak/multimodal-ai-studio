# Design and operating boundaries

Prompt-to-edit planning prototype that converts supported phrases into ordered media-operation specifications.

## Scope

This library generates plans only. It does not upload, decode, edit or generate media, run segmentation models, produce subtitles, or render a timeline. Intent detection uses keywords; negation and complex mixed intents are not understood. Validation detects duplicates, not complete parameter or media compatibility. No API, UI or external services are included.

## Interfaces

Implementation lives in `src/multimodal_studio/`. Public examples in the README use its Python API. This project is a library, without a service layer.

## Validation

Tests include synthetic regression fixtures. Package and container checks verify installation separately from source-tree imports. Tests do not certify general model quality, clinical correctness or multi-tenant isolation.

## Planned evolution

Typed parameter validation; media metadata ingestion; preview executor with FFmpeg; model adapters; timeline UI.
