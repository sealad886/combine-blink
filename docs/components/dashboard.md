# Pipeline Dashboard

`PipelineDashboard` (`blink_pipeline/pipeline_dashboard.py`) provides a Rich Live view of
the entire pipeline. It replaces the legacy `ProgressTracker` while preserving
fully programmatic control over stages and substages.

## Layout & Refresh

- Three-row Rich layout: header (title + elapsed/ETA), main (stage overview table
  + current stage panel), footer (aggregate statistics).
- Refresh rate: 4 Hz by default, sufficient to feel real-time without saturating
  the terminal.
- Automatically starts/stops via context-manager protocol (`with dashboard:`).
- Header ETA is computed from completed stages; per-stage ETA appears in the
  overview table when a stage is running.

## Stage Tracking API

| Method | Purpose |
|--------|---------|
| `start_stage(stage_key, total=None)` | Mark stage as running and optionally override the item count. |
| `update_stage(stage_key, completed, details="")` | Update completion count and optional detail string. |
| `complete_stage(stage_key, details="")` | Mark as complete, persisting end time and summary. |
| `skip_stage(stage_key, reason="")` | Mark as skipped and annotate the reason. |
| `start()` / `stop()` | Manual control when context manager is not used. |
| `print_summary()` | Emit final summary table (auto-called on exit). |

Stage keys matching the orchestrator: `validation`, `transcription`, `speaker_id`,
`merge`.

## Substage Tracking

- `add_substage(stage_key, name, total)` inserts an item under the current stage.
- `update_substage(stage_key, name, progress)` increments progress and starts the
  elapsed timer when progress first exceeds 0.
- `remove_substage(stage_key, name)` hides the entry upon completion.
- Each substage tracks:
  - `progress` / `total` (rendered as 10-character bar + count).
  - `visible` (workers can hide themselves when done).
  - `start_time` + `end_time`: ensure elapsed time reflects processing only (no
     queue time).

The current stage panel shows the top 10 active substages with elapsed times (`—`
for queued items that have not started yet).

## Worker Integration Pattern

```python
with multiprocessing.Manager() as manager:
    shared = manager.dict()

    with ProcessPoolExecutor(max_workers=workers) as executor:
        for group_name, job in jobs:
            dashboard.add_substage(stage_key, group_name, job.total_clips)
            task_id = f"{stage_key}_{group_name}"
            args = (*job.args, shared, task_id)
            futures[executor.submit(worker, args)] = (group_name, task_id)

        while not all(f.done() for f in futures):
            for task_id, payload in shared.items():
                if payload.get("visible", True):
                    group = task_id.split("_", 1)[1]
                    dashboard.update_substage(stage_key, group, payload["progress"])
            time.sleep(0.1)
```

Workers should post dictionaries shaped like:

```python
{
    "progress": completed_clips,
    "total": total_clips,
    "visible": True
}
```

## Resume Awareness

- Stage details can be edited before `start_stage` to communicate resume state
  (e.g., `"Resuming: 3 already complete"`).
- Completed work that is pre-detected (existing transcripts/videos) can be counted
  in `completed` so the progress bar instantly reflects inherited progress.

## Error Handling

- Stage status toggles from `RUNNING` → `ERROR` when any exception bubble is
  surfaced via orchestrator hooks (e.g., Stage 5 counts failures).
- Substages can stay visible after failure by skipping `remove_substage` and
  setting `visible=False` in the payload to hide them from the table.

## Tests

The dashboard has focused coverage:

- `test_dashboard.py`: stage lifecycle and summarized statistics.
- `test_dashboard_eta.py`: ETA calculation accuracy.
- `test_substage_timing.py` / `test_substage_timing_visual.py`: queue-aware timing.
- `test_timing_display.py`: ensures formatted elapsed times render correctly.
- `test_substage_comprehensive.py`: regression suite covering add/update/remove flows.

Whenever you extend dashboard features, add/adjust tests here so they remain a
reliable guide for orchestrator behaviour.

## Migration Notes (Legacy `ProgressTracker`)

- Stage keys map from numeric `ProgressTracker` indices → named strings.
- Per-group progress that used to rely on Rich tasks now lives inside substages.
- Logging calls (`log_info`/`log_warning`) should switch to the unified pipeline
  logger; the dashboard is presentation-only.
- The legacy tracker remains for demos/tests; see
  [`legacy/progress_tracker.md`](../legacy/progress_tracker.md) if you need a
  side-by-side comparison.
