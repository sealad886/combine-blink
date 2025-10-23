# Orchestrator Concurrency Refactor Plan

## Why change it
- `blink_pipeline/orchestrator.py:360-470` and `blink_pipeline/orchestrator.py:520-650` mix `multiprocessing.Manager` primitives with `concurrent.futures.ProcessPoolExecutor`. This works, but it layers two concurrency abstractions that both spawn processes and manage IPC, increasing startup cost and the chance of cross-platform issues (e.g. `fork` vs `spawn` semantics on macOS/Windows).
- The shared dictionaries created by the `Manager` are polled in tight loops for progress updates, which adds constant IPC chatter and has already shown ~8–10% CPU overhead in local profiling.
- Worker initialisation (logging, dashboard awareness) is duplicated between Stage 3 and Stage 5, making changes error-prone and hiding subtle differences (e.g. transcription jobs track per-clip progress, merge jobs also stash `start_time`).
- Cancellation/retry behaviour is inconsistent: `KeyboardInterrupt` is handled around the outer pool, but child processes keep running until they notice, so the dashboard can freeze for ~30s after Ctrl+C.

## Goals
1. Own the process orchestration in one place so future stages can reuse it without copy-paste.
2. Replace the Manager-backed polling dict with a lightweight, explicit progress channel.
3. Make worker setup (logging, config fragments) uniform and testable.
4. Ensure clean cancellation and better error surfacing (single failure should not hang all results).

## Proposed updates

1. **Add a pipeline worker harness**
   - New module: `blink_pipeline/pipeline_pool.py`.
   - Responsibilities:
     - Wrap a `multiprocessing.get_context("spawn").Pool` or `ProcessPoolExecutor` (final choice after benchmarking) behind a `PipelineWorkerPool` class.
     - Provide a `submit()` API that accepts the callable, its payload, and an optional `ProgressConsumer`.
     - Spin up a dedicated background thread that drains a `multiprocessing.Queue` carrying progress events (`{"task_id": ..., "completed": ..., "total": ...}`), forwarding them to the dashboard.
     - Handle graceful shutdown (`close`, `cancel_pending`, `terminate`) and translate worker exceptions into structured `PipelineTaskError` objects.

2. **Refactor progress communication**
   - Replace the Manager `dict` with a `multiprocessing.Queue` created by the harness.
   - Worker signatures (`_transcribe_group_job`, `_merge_group_job`) gain an optional `ProgressReporter` callable injected by the harness and use it directly instead of mutating shared state.
   - Update workers to call `ProgressReporter(report=ProgressUpdate(...))` instead of touching shared dicts.

3. **Stage 3 (Transcription) integration**
   - Modify `blink_pipeline/orchestrator.py` around `dashboard.start_stage('transcription'…)` to:
     - Instantiate `PipelineWorkerPool(max_workers=transcribe_workers, stage='transcription')`.
     - Submit jobs with task metadata (`task_id`, `group_name`, `video_paths`, `config`).
     - Move the progress monitoring loop into the harness, leaving only high-level dashboard updates in the orchestrator.
   - When results arrive, update `stage3_results` and transcripts exactly as today, but without manual `future` bookkeeping.

4. **Stage 5 (Merge/Composition) integration**
   - Apply analogous changes in `blink_pipeline/orchestrator.py` within the merge stage.
   - Ensure `_merge_group_job` receives the `ProgressReporter`; drop the Manager-specific code that rehydrates `start_time`.
   - Normalise success/failure accounting so the dashboard reflects completed work immediately on worker return.

5. **Worker bootstrap improvements**
   - Move the logging setup currently duplicated in `_transcribe_group_job` and `_merge_group_job` into a shared helper (`blink_pipeline/logging_config.py` already exposes `configure_worker_logging`).
   - The harness should call an `initializer` that runs `configure_worker_logging` and seeds stage-specific context (e.g. stage label for loggers).
   - Document any new environment variables or config knobs in `docs/components/pipeline.md` (new section on concurrency controls).

6. **Tests and validation**
   - Add unit coverage for the harness (`tests/unit/test_pipeline_pool.py`) verifying:
     - Progress events hit the consumer in order.
     - Exceptions propagate and include task metadata.
   - Update integration smoke test (`tests/integration/test_media_validation.py`) or add a new pipeline smoke test that exercises both stages with `max_workers=2` to confirm it stays functional.
   - Manual QA checklist: run `pytest tests/unit/test_people_detection.py` (ensures dependent modules still import), and invoke the CLI pipeline on a small sample to verify dashboard behaviour.

## Risks & mitigations
- **Behavioural parity:** ensure transcription and merge workers still see the same config and progress semantics by snapshotting all inputs in serialisable dataclasses.
- **Spawn vs fork differences:** force `spawn` context so the plan works uniformly on macOS and Windows; update documentation to mention the change.
- **Throughput regression:** benchmark old vs new harness on 2× and 4× worker counts; keep Manager-based path behind a feature flag `USE_LEGACY_POOL` (default false) in case we need rollback.
