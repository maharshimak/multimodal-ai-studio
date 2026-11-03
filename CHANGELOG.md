# Changelog

All notable engineering changes to this repository are documented here.

The format follows the intent of [Keep a Changelog](https://keepachangelog.com/) and uses semantic versioning principles where releases are created.

## [Unreleased]

### Media engine
- Fixed: `trim` now always runs before `retime`; previously alphabetical ordering applied trim bounds to the retimed timeline.
- Fixed: fractional pixel parameters, unknown parameters and non-numeric values are rejected with `PlanValidationError` instead of being truncated, ignored or raising `TypeError`.
- Fixed: an infinite frame rate from ffprobe is treated as unknown.
- Added exact rational frame/duration arithmetic, plan-vs-media projection, output duration/resolution budgets and SHA-256 artifact verification.
- Added the `makma.v1` contract (`plan`, `execute`, `verify_artifact`).

### Engineering
- Added repository ownership and structured contribution workflows.
- Added Dependabot coverage for Python and GitHub Actions dependencies.
- Added issue and pull-request templates focused on reproducibility, validation, risk, and rollback.
- Added consistent editor configuration and engineering standards.

## Release policy

A release should describe user-visible behavior, compatibility notes, validation evidence, and any migration or rollback requirements. Repository history remains the source of truth for individual commits.
