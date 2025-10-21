# Blink Pipeline Documentation

This directory collects the living documentation for the Blink video processing
pipeline. It is intentionally organized by audience so you can jump straight to
what you need.

- **Getting Started**
  - [`overview.md`](overview.md) — end-to-end pipeline walkthrough (stages, resume flow, outputs).
  - [`reference/configuration.md`](reference/configuration.md) — annotated `config.yaml`.
  - [`../ALIGNMENT_ALGORITHM.md`](../ALIGNMENT_ALGORITHM.md) — robust multi-window GCC‑PHAT alignment and audio stitching details.
- **Core Components**
  - [`components/dashboard.md`](components/dashboard.md) — Rich dashboard API and integration tips.
  - [`components/media-validation.md`](components/media-validation.md) — Stage 0 validation, cache format, progress callbacks.
  - [`components/resume.md`](components/resume.md) — File-based resume behaviour for transcripts and merges.
  - [`components/logging.md`](components/logging.md) — Logging architecture, log files, and troubleshooting.
- **Reference & Appendices**
  - [`reference/tests.md`](reference/tests.md) — map of automated test modules to the behaviour they cover.
  - [`reference/output.md`](reference/output.md) — what to expect in `output/` after a run.
- **History & Context**
  - [`history/changelog.md`](history/changelog.md) — notable feature batches.
  - [`history/optimizations.md`](history/optimizations.md) — performance and reliability improvements that shaped Stage 0.
- **Legacy Notes**
  - [`legacy/progress_tracker.md`](legacy/progress_tracker.md) — archived Rich progress tracker retained for demos/tests.

When adding new documentation, prefer extending one of these files (or adding a
new one under the matching subdirectory) rather than placing markdown in the
repository root. This keeps the top level tidy and makes it trivial to find
related material.
