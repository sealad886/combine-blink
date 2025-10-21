# Automated Test Suite

The repository ships with focused scripts (prefixed `test_*.py`) that exercise
individual pipeline components. Many are runnable demos rather than strict unit
tests, but each documents expected behaviour. This table summarises coverage.

| Test file | Focus |
|-----------|-------|
| `test_dashboard.py` | Happy-path dashboard walkthrough (stages, substages, summary). |
| `test_dashboard_eta.py` | Visual confirmation of stage/header ETA calculations under slower workloads. |
| `test_substage_comprehensive.py` | Regression test for add/update/remove substage flows (including visibility). |
| `test_substage_timing.py` / `test_substage_timing_visual.py` | Verifies queue-aware substage timing (elapsed starts on first progress tick). |
| `test_timing_display.py` | Ensures timing text renders correctly within the dashboard panel. |
| `test_merge_clips.py` | Demonstrates merge-stage substages showing actual clip counts. |
| `test_stage3_progress.py` | Runs the orchestrator with one worker to confirm Stage 3 progress updates per clip. |
| `test_progress.py` | Legacy Rich `ProgressTracker` demo retained for comparison/diagnostics. |
| `test_logging.py` | Confirms `PipelineLogger` and worker logging configuration (handlers, rotation, levels). |
| `test_filename_parsing.py` | Exercises `discover_files` regex parsing and date extraction. |
| `test_grouping.py` | Validates time-based grouping into multi-camera events. |
| `test_unified_repair.py` | Verifies Stage 0 cache mapping and statistics. |
| `test_video_repair.py` | Low-level ffmpeg repair routine validation. |
| `test_repair_strategies.py` / `test_repair_strategies_real.py` | Coverage for `fill` vs `remove_blank` repair strategies on sample media. |
| `test_optimizations.py` | Guardrails around Stage 0 optimisations (hashing, worker init, status tracking). |
| `test_resume_capability.py` | Confirms resume detection for transcripts/videos. |
| `test_resume_integration.py` | Ensures orchestrator integrates resume state across stages. |

Most scripts can be executed directly:

```bash
python test_dashboard.py
python test_unified_repair.py
```

When adding new behaviour, extend or duplicate the closest existing test so
observability remains high. For end-to-end validation, prefer targeted scripts
over a single monolithic test to keep iteration fast.
