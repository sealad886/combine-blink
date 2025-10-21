# Stage 3 Progress Bar Fix

## Problem
Progress bars in Stage 3 (Transcription & Diarization) were not updating during processing. They would appear and then disappear when complete, with no intermediate progress shown.

## Root Cause
The `_transcribe_group_job` worker was using a binary progress model:
- Set progress to 0/1 at start
- Set progress to 1/1 at end
- No updates during the actual transcription of multiple clips

This made it impossible to see which clips were being processed and how far along each group was.

## Solution
Modified the progress tracking to be **per-clip** instead of per-group:

### Changes Made

1. **orchestrator.py** - `_transcribe_group_job`:
   - Changed `total` from 1 to `len(video_paths)` (actual number of clips)
   - Added `progress_callback` function to update shared dict
   - Passed callback to `process_audio_for_transcription`

2. **transcription.py** - `process_audio_for_transcription`:
   - Added optional `progress_callback` parameter
   - Calls `progress_callback(index + 1)` after completing each clip
   - Progress updates happen after each clip's transcription + diarization

### Result
Now Stage 3 progress bars show:
- **Total**: Number of clips in the group (e.g., 5)
- **Progress**: Number of clips completed so far (e.g., 3/5)
- Updates happen in real-time as each clip completes

### Example
Before:
```
Group_20251015_110921: [                    ] 0/1
Group_20251015_110921: [Done]               (task disappears)
```

After:
```
Group_20251015_110921: [████                ] 2/5
Group_20251015_110921: [████████            ] 4/5
Group_20251015_110921: [████████████████████] 5/5 (task disappears)
```

## Testing
Run the pipeline normally - Stage 3 progress bars should now update as each clip in a group is transcribed and diarized.

For focused testing:
```bash
python test_stage3_progress.py
```

This runs the full pipeline with Stage 3 visible, using a single worker for easier observation.
