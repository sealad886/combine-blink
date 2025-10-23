# Stage 3 Caching Implementation

## Problem
Stage 3 (Transcription & Diarization) was re-processing all audio from scratch on every pipeline run because there was no caching mechanism. This is extremely expensive since it:
- Runs Whisper.cpp transcription on each clip
- Runs pyannote speaker diarization on each clip
- Does speaker assignment/matching
- Can take many minutes per group

The code only checked for transcript *text files* (written in Stage 4), not the actual diarization data from Stage 3.

## Solution
Added diarization result caching in `output/.diarization_cache/`:

### Cache Structure
- Location: `output/.diarization_cache/{group_name}_diarization.json`
- Format:
  ```json
  {
    "group_name": "20251015_083743_Corner+Entry+Frontdoor",
    "processed_paths": ["/path/to/repaired/video1.mp4", ...],
    "diarization_result": {
      "segments": [
        {"start": 0.0, "end": 4.2, "speaker": "SPEAKER_00", "text": "..."},
        ...
      ],
      "timeline": [...]
    },
    "timestamp": "2025-10-22T21:45:00"
  }
  ```

### Implementation Details

1. **Worker Cache Check** (`_transcribe_group_job`):
   - Checks for cached result at start of job
   - If found: loads from cache, updates progress to 100%, returns immediately
   - If not found or invalid: proceeds with normal processing

2. **Cache Write**:
   - After successful transcription/diarization
   - Writes atomic (temp file + rename)
   - Non-fatal if caching fails (logs warning)

3. **Dashboard Integration**:
   - Reports number of cached results found at stage start
   - Updates progress normally (cached results complete instantly)

### Benefits
- **Massive time savings** on repeat runs (seconds vs minutes per group)
- **Preserves speaker assignments** across runs
- **Enables fast iteration** on downstream stages (merge, final transcription)
- **Safe resume** after interruption

### Usage
- Cache is automatic - no configuration needed
- Cache directory: `output/.diarization_cache/`
- To force re-transcription: delete cache directory or specific JSON files
- Cache includes timestamp for tracking/debugging

## Files Modified
- `blink_pipeline/orchestrator.py`:
  - Added cache check at start of `_transcribe_group_job()`
  - Added cache write after successful processing
  - Updated Stage 3 logging to report cached results

## Example Output
```
STAGE 3: Transcription & Diarization - START
  14 groups, 2 workers
Found 12 cached diarization results
Processing 2/14 groups
```

## Next Steps
Pipeline will now:
1. Use cached diarization for groups that were already processed
2. Only transcribe/diarize new or modified groups
3. Run significantly faster on subsequent executions
