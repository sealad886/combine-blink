# Legacy Progress Tracker

`blink_pipeline/progress.py` contains the original Rich progress tracker used before the
full `PipelineDashboard` was introduced. It remains in the codebase for demo
purposes (`test_progress.py`) and as a lightweight reference for scripts that
don’t require the full dashboard layout.

## Capabilities

- Stage headers printed with emoji and ASCII separators.
- `create_progress()` helper returns a Rich `Progress` instance configured with
  spinner, bar, percentage, and time columns.
- Simple logging helpers (`log_info`, `log_warning`, `log_error`) output
  colour-coded messages without touching the main logger.

## Limitations (Why Dashboard Replaced It)

- No unified view of multiple stages or substages.
- ETA calculations were manual and less accurate.
- No resume awareness or summarised statistics.
- Harder to integrate with multiprocessing without custom wiring.

## When to Use

- Quick demonstrations or tests where the full dashboard overhead is not needed.
- Regression comparison when tweaking Rich layouts.

For all pipeline runs, prefer `PipelineDashboard`. See
[`../components/dashboard.md`](../components/dashboard.md) for the modern API.
