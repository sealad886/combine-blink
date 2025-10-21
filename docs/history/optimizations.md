# Stage 0 Optimisation Record

This log tracks the targeted optimisations applied to media validation and
related tooling. Use it when evaluating further performance work so previous
decisions are visible.

## Phase 1 (Completed)

1. **Accurate Status Tracking**
   - Worker return value changed from `(path, validated_path, bool)` to `(path, validated_path, status)` with explicit statuses (`"cached"`, `"repaired"`, `"original"`).
   - Statistics in `preprocess_videos` now report repaired vs cached distinctly.
   - Logging summarises all three counts for transparency.

2. **Worker Initialisation**
   - Added `_init_worker()` to configure logging exactly once per child process.
   - Removed per-video logging level changes inside `_validate_video_job`.

3. **Collision-Safe Cache Keys**
   - Cache filenames now append an 8-character hash of the absolute path.
   - Legacy filenames (`repaired_{strategy}_{filename}`) are auto-migrated.
   - Prevents cross-directory collisions when cameras emit identical filenames.

4. **Progress Persistence**
   - `.preprocessing_progress.json` introduced to resume Stage 0 after interrupts.
   - Saved atomically (temp file + rename) to avoid corruption.

## Candidate Ideas (Backlog)

The following opportunities were identified but not pursued yet. Revisit when
profiling shows Stage 0 as a bottleneck.

- **Two-phase cache check**: thread-pool pre-check of cache hits to avoid spawning
  process workers unnecessarily.
- **Batch processing**: submit videos to workers in batches to cap memory usage on
  very large inputs.
- **Extended telemetry**: record repair duration per file to spot outliers.

If you implement any of the backlog items, update this document with the date,
change summary, and measured impact.
