# High-Level Changelog

This changelog captures the major feature batches that shaped the current
pipeline. For granular implementation details refer to git history or the
linked component docs.

## 2025-10-21 — Robust Multi-Window Audio Alignment & Stitching

- Replaced single-window cross-correlation with multi-window GCC-PHAT time delay
  estimation using robust median aggregation.
- Added optional linear drift estimation (seconds per second) to compensate for
  slow clock differences between cameras.
- Base offsets applied to video clip start times; time-varying correction
  (base + drift × t) applied to audio segment extraction.
- Introduced audio crossfade stitching using FFmpeg `acrossfade` filter with
  triangular curves to eliminate clicks at segment boundaries.
- New configuration keys:
  - `multi_camera_composition.audio_alignment.hop_seconds`
  - `multi_camera_composition.audio_alignment.estimate_drift`
  - `multi_camera_composition.audio_crossfade_seconds`
- Added `src/av_alignment.py` module with `estimate_offsets_and_drift()` and
  `gcc_phat()` implementations.
- Documentation: `ALIGNMENT_ALGORITHM.md` for algorithm details; updated
  `README.md` and `docs/reference/configuration.md` with new settings.
- Test coverage: `test_av_alignment.py` for basic GCC-PHAT sanity checks.

## 2025-10-15 — Pipeline Dashboard Rollout

- Replaced legacy `ProgressTracker` with `PipelineDashboard` for a unified Rich
  UI (stages + substages + stats).
- Added ETA calculations, resume awareness, substage elapsed timers, and clip-aware
  progress updates.
- Test coverage expanded (`test_dashboard.py`, `test_dashboard_eta.py`,
  `test_substage_*`, `test_merge_clips.py`) to lock in behaviour.
- Introduced documentation at `docs/components/dashboard.md`.

## 2025-10-14 — Resume & Stage 5 Enhancements

- Added file-based resume detection for transcripts and merged videos.
- Success counts now include resumed work; dashboard details highlight how many
  groups were skipped.
- Stage 5 enriched with per-group clip counts and substage progress reporting.
- See [`components/resume.md`](../components/resume.md) for runbook details.

## 2025-10-13 — Stage 0 Unification

- Centralised media validation/repair in a dedicated Stage 0 with process-pool
  execution.
- Introduced collision-safe cache filenames, cached-vs-repaired statistics, and
  atomic progress persistence.
- Updated orchestrator to apply validated paths ahead of transcription.
- See [`components/media-validation.md`](../components/media-validation.md).

## 2025-10-12 — Multi-Camera Composer Upgrade

- Expanded `MultiCameraComposer` with audio-driven camera switching, optional
  crossfade transitions, fine audio alignment, and timestamp overlay support.
- Added configuration knobs under `multi_camera_composition`.
- Documented in [`overview.md`](../overview.md) (Stage 5 section).

## 2025-10-11 — Logging Overhaul

- Introduced `PipelineLogger` with rotating logs (main/errors) plus per-session
  archival files.
- Workers now attach to the same log configuration via `configure_worker_logging`.
- Documented in [`components/logging.md`](../components/logging.md).

## Earlier Changes

Earlier iterations focused on foundational modules (discovery, grouping,
transcription). Refer to git history or legacy documents in `docs/legacy/` if
you need context predating the upgrades above.
