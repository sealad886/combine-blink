# Unified Repair Cache System

## Summary

Refactored the video repair system to use a **single preprocessing stage** (Stage 0) that validates and repairs all videos **exactly once** before the main processing pipeline begins.

## Problem Solved

**Before:**
- Videos were repaired on-demand during transcription (Stage 3)
- Two separate cache directories: `output/repair_strategy_cache` and `output/repaired_cache`
- Same video could be repaired multiple times
- Repair logic embedded in transcription code
- Later stages didn't know if videos were valid or needed repair

**After:**
- All videos validated and repaired upfront in Stage 0
- Single unified cache directory: `output/repaired_cache`
- Each video repaired at most once
- Repair logic centralized in `src/media_validation.py`
- Later stages work with validated files only

## Architecture Changes

### New Module: `src/media_validation.py`

```python
def preprocess_videos(
    video_paths: List[str],
    cache_dir: str,
    strategy: str = "fill",
    always_repair: bool = False,
    max_workers: int = 3,
    progress_callback=None
) -> Dict[str, str]:
    """
    Validate and repair all videos upfront, returning a path mapping.

    Returns:
        Dictionary mapping original_path → validated_path
        (validated_path is either repaired cache path or original if no repair needed)
    """
```

**Key Functions:**
- `preprocess_videos()`: Main preprocessing function, returns original→repaired path mapping
- `get_validation_stats()`: Analyzes path mapping for statistics
- `_validate_video_job()`: Worker function for parallel validation/repair

### Modified: `src/orchestrator.py`

**Added Stage 0 (after Stage 2 grouping, before progress tracker):**

```python
# --- STAGE 0: Video Validation & Repair (Preprocessing) ---
all_video_paths = [extract all unique paths from groups]

path_mapping = preprocess_videos(
    all_video_paths,
    repair_cache_dir,
    strategy=repair_strategy,
    always_repair=always_repair,
    max_workers=validation_workers,
    progress_callback=update_progress
)

# Apply path mapping to all video groups
for group in video_groups:
    for clip in group:
        clip['full_path'] = path_mapping.get(clip['full_path'], clip['full_path'])
```

**Flow:**
1. Discover all videos
2. Group videos
3. **Stage 0: Validate/repair all unique videos → get path mapping**
4. Apply path mapping to all groups
5. Stage 3: Transcription (works with validated paths)
6. Stage 4: Speaker identification
7. Stage 5: Merging/composition

### Modified: `src/transcription.py`

**Removed:**
- `repair_video` import
- Repair cache directory creation
- Repair logic in processing loop
- `needs_repair` detection
- `video_to_process` variable
- Repaired path tracking in timeline

**Simplified to:**
```python
# Probe video metadata (all videos are pre-validated in Stage 0)
media_info = probe_media_info(path)

# Create timeline entry (path already points to validated/repaired video)
clip_entry = {
    "path": path,
    "offset": running_offset,
    "duration": media_info.duration,
    "has_audio": media_info.has_audio,
}
```

### Modified: `config.yaml`

**Updated transcription section:**
```yaml
transcription:
  # Video Validation & Repair (Stage 0 - Preprocessing)
  # All discovered videos are validated and repaired upfront before transcription.
  # This ensures each video is repaired exactly once, with results cached for subsequent runs.

  always_repair: false  # Only repair videos with audio/video sync issues (>100ms difference)
  repair_cache_dir: output/repaired_cache  # Single unified cache directory
  repair_strategy: fill  # 'fill' (recommended) or 'remove_blank'
```

## Benefits

1. **Single Source of Truth**: One cache directory for all repaired videos
2. **Efficiency**: Each video repaired exactly once, cached for subsequent runs
3. **Clarity**: Clear separation between validation and processing
4. **Progress Visibility**: Users see repair progress upfront, not hidden in transcription
5. **Simplicity**: Later stages don't need repair logic
6. **Consistency**: All stages work with validated files

## Migration Guide

### For Existing Users

1. **Update config.yaml**: Add `repair_strategy` setting (see above)
2. **Clean up old caches and test outputs**:
   ```bash
   python cleanup_repair_cache.py
   ```
   This script will:
   - Remove old `repair_strategy_cache` directory
   - Move stray repaired videos from `output/` root to `output/test_repairs/`
   - Display current cache structure

   Alternatively, manual cleanup:
   ```bash
   rm -rf output/repair_strategy_cache
   mkdir -p output/test_repairs
   mv output/*_fill.mp4 output/test_repairs/ 2>/dev/null || true
   mv output/*_remove_blank.mp4 output/test_repairs/ 2>/dev/null || true
   ```
3. **Run pipeline**: Stage 0 will appear before transcription

### Cache Reuse

The new system is designed to **reuse existing cached repairs**:
- If `output/repaired_cache` exists with repaired videos, they will be used
- No need to re-repair videos that are already in cache
- Cache format is compatible (same naming scheme)

### Testing

Run the test script to validate the system:
```bash
python test_unified_repair.py
```

This will:
- Test repair on a subset of videos
- Verify cache reuse
- Confirm path mappings are consistent

## Configuration Options

```yaml
transcription:
  # always_repair: If true, repair ALL videos regardless of detected issues
  #                If false, only repair videos with audio/video sync issues
  always_repair: false

  # repair_cache_dir: Single unified cache directory for all repaired videos
  repair_cache_dir: output/repaired_cache

  # repair_strategy: How to handle damaged/corrupted video frames
  #   - 'fill': Duplicate last good frame for missing sections (recommended)
  #   - 'remove_blank': Remove blank/static frames using mpdecimate filter
  repair_strategy: fill
```

## Stage 0 Output Example

```
================================================================================
🔍 STAGE 0: Video Validation & Repair
================================================================================

Validating 47 unique video files...
Cache directory: output/repaired_cache
Repair strategy: fill
Always repair: No (only when needed)

Validating videos ████████████████████████ 100% • 47/47 videos

✓ Validation complete:
  • 47 videos processed
  • 12 repaired/cached
  • 35 used as-is

================================================================================
```

## Technical Details

### Multi-Processing Architecture

Stage 0 validation uses **true multi-processing** (not threading) for maximum performance:

```python
# From src/media_validation.py
with ProcessPoolExecutor(max_workers=max_workers) as executor:
    futures = {executor.submit(_validate_video_job, job): job[0] for job in jobs}
    for future in as_completed(futures):
        # Process results as they complete
```

**Why Multi-Processing?**
- Each worker is an independent process (bypasses Python GIL)
- ffmpeg operations are CPU and I/O intensive
- Repairs happen in parallel, limited only by disk I/O
- Progress updates in real-time as jobs complete

**Worker Job:**
1. Check cache first (fast path - no ffmpeg needed)
2. Probe video with ffmpeg (detect sync issues)
3. Repair if needed (ffmpeg re-encode)
4. Cache result for future runs

**Performance Characteristics:**
- **Cache hits:** Very fast (~100-500ms per video)
- **Repairs:** Slower (~5-30s per video, depends on length/resolution)
- **Bottleneck:** Usually disk I/O, not CPU
- **Scaling:** Linear up to I/O saturation point

**Configuration:**
```yaml
concurrency:
  validation_workers: 2  # Start here, adjust based on system
```

### Path Mapping

The core of the system is the path mapping dictionary:
```python
{
    "25-10-15/08-37-43_CornerG8T1K0013255014P_081.mp4": "output/repaired_cache/repaired_fill_08-37-43_CornerG8T1K0013255014P_081.mp4",
    "25-10-15/08-37-55_EntryG8T1K0013255014H_080.mp4": "25-10-15/08-37-55_EntryG8T1K0013255014H_080.mp4",  # No repair needed
    ...
}
```

This mapping is applied to all video groups before processing begins.

### Repair Detection

A video needs repair if:
1. `always_repair = true` in config, OR
2. Audio/video duration difference > 100ms

Detection logic:
```python
media_info = probe_media_info(video_path)
duration_diff = abs(media_info.video_duration - media_info.audio_duration)
needs_repair = duration_diff > 0.1  # More than 100ms
```

### Cache Format

Cached files are named: `repaired_{strategy}_{original_filename}`

Example:
- Original: `08-37-43_CornerG8T1K0013255014P_081.mp4`
- Cached: `repaired_fill_08-37-43_CornerG8T1K0013255014P_081.mp4`

## Troubleshooting

### "Cache directory not created"
- Check permissions on `output/` directory
- Verify `repair_cache_dir` path in config.yaml

### "Same video repaired multiple times"
- This should not happen with the new system
- If it does, file a bug report with logs

### "Stage 0 is slow"
- Adjust `concurrency.validation_workers` in config.yaml
- Stage 0 is **already multi-processed** using ProcessPoolExecutor
- Default: 2 workers (safe for most systems, avoids disk I/O saturation)
- **Scaling advice:**
  - **SSD systems**: Can use 3-4 workers safely
  - **HDD systems**: Keep at 2 workers (I/O is the bottleneck)
  - **High-end systems**: Try 4-6 workers, but watch disk I/O metrics
  - Each worker runs ffmpeg which is multi-threaded internally
  - More workers ≠ faster if disk I/O is saturated

### "Repaired videos in output/ root directory"
- These are from old test scripts (`test_repair_strategies*.py`)
- Run `python cleanup_repair_cache.py` to organize them into `output/test_repairs/`
- Updated test scripts now use proper directory structure:
  - Cache: `output/repaired_cache/` (unified cache, reused by pipeline)
  - Test outputs: `output/test_repairs/` (separate from production)

## Future Enhancements

Possible improvements:
- [ ] Parallel progress bars per video (like Stage 3)
- [ ] Repair quality metrics and validation
- [ ] Support for additional repair strategies
- [ ] Automatic strategy selection based on damage type
- [ ] Cache cleaning/management tools

## Code Review

All changes have been validated:
- ✅ No compilation errors
- ✅ Clean control flow and nesting
- ✅ Thread-safe shared dict usage
- ✅ Proper resource cleanup
- ✅ Comprehensive error handling

See: `CODE_REVIEW_VALIDATION.md` for detailed structural analysis.
