# Stage 0 — Media Validation & Repair

Stage 0 ensures every discovered clip is probed, repaired when necessary, and
cached before the heavy transcription work begins. Implementation lives in
`blink_pipeline/media_validation.py`.

## Goals

- **Single pass**: each raw video is validated or repaired exactly once per run.
- **Cache reuse**: repaired outputs are written to a unified cache that’s safe
  across directory structures.
- **Deterministic statistics**: track freshly repaired vs cached vs untouched clips.
- **Interruption resilience**: progress is persisted so restarts can resume Stage 0
  without rework.

## Execution Flow

1. The orchestrator aggregates unique clip paths across all groups.
2. `preprocess_videos` runs inside a `ProcessPoolExecutor` with an
   `_init_worker` initializer that sets a quiet logging level.
3. Each worker performs:
   - Cache lookup using `_get_cache_path` (hashes the full path to prevent
     collisions) with legacy-name migration.
   - `probe_media_info` to detect audio/video duration mismatch and metadata.
   - Conditional repair (`repair_video`) when `always_repair` is true or the
     duration delta exceeds 100 ms.
   - Status return tuple: `(original_path, validated_path, status)` where status
     is `"cached"`, `"repaired"`, or `"original"`.
4. The manager process updates a progress callback for the dashboard and builds
   a mapping `original_path → validated_path`.
5. Statistics are summarised via `get_validation_stats` and displayed both in
   the dashboard and stdout.
6. The orchestrator overwrites each group clip’s `full_path` with the validated
   path so downstream stages are unaware of the repair step.

## Cache Format

- Location: `transcription.repair_cache_dir` (default `output/repaired_cache`).
- Filename template: `repaired_{strategy}_{stem}_{hash8}.mp4`.
- Hash: BLAKE2s (8 hex chars) digest of the absolute input path for collision resistance.
- Legacy files named `repaired_{strategy}_{filename}` are migrated in-place on
  discovery.
- A hidden JSON file `.preprocessing_progress.json` stores progress to support
  restarts mid-stage.

## Repair Strategies

Controlled by `transcription.repair_strategy`:

- `fill` (default): duplicates the last good frame to bridge gaps, keeping audio.
- `remove_blank`: drops frozen frames using `mpdecimate`.

Repairs run via ffmpeg with:

- Video filters: `fps`, `trim`, `setpts`.
- Audio filters: `apad` to pad silence when needed.
- Encoding: `libx264` with `-preset fast`, `-crf 23`, `aac` audio, `+faststart`.
- Error tolerance: `-err_detect ignore_err`.

## Configuration Summary

```yaml
transcription:
  always_repair: false        # repair only when needed
  repair_cache_dir: output/repaired_cache
  repair_strategy: fill
```

See [`reference/configuration.md`](../reference/configuration.md) for the full
context and additional options.

## Progress & Telemetry

- Workers call `progress_callback(completed, total)` once per clip.
- The dashboard renders Stage 0 with total unique clips; substages are not used
  here to keep the view concise.
- Summary prints the counts for repaired, cached, and original clips; logging
  mirrors the same via `PipelineLogger`.

## Tests

- `test_unified_repair.py`: cache reuse and mapping correctness.
- `test_repair_strategies.py` / `test_repair_strategies_real.py`: strategy-specific
  behaviour on sample media.
- `test_video_repair.py`: low-level ffmpeg invocation correctness.

Use these tests when modifying media validation to avoid regressing cache format,
statistics, or convergence guarantees.
