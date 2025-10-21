# Resume Functionality Documentation

## Overview

The Blink video processing pipeline now includes **automatic resume functionality** that allows it to pick up where it left off if interrupted (via Ctrl+C, system crash, etc.). This prevents wasted processing time by skipping groups that have already been completed.

## How It Works

The pipeline detects completed work by checking for the existence of output files:

### Stage 3: Transcription & Diarization
- **Detection**: Checks for existing transcript files in `output/transcripts/`
- **File pattern**: `{group_name}_transcript.txt`
- **Behavior**:
  - If transcript exists for a group, that group is skipped
  - The original video paths are still tracked for Stage 5 merging
  - Progress counter includes both new and skipped groups

### Stage 4: Speaker Identification
- **Note**: This stage is **serial and dependent on Stage 3**
- If a transcript already exists, speaker identification was already completed
- No separate resume logic needed (handled by Stage 3 skip)

### Stage 5: Video Merging
- **Detection**: Checks for existing merged videos in `output/merged_videos/`
- **File pattern**: `{group_name}_merged.mp4`
- **Behavior**:
  - If merged video exists for a group, that group is skipped
  - Progress counter includes both new and skipped groups
  - Success count includes existing videos

## Example Scenario

### Initial Run (Interrupted)
```bash
$ python main.py

🎬 BLINK VIDEO PROCESSING PIPELINE
================================================================================

📁 Found 15 video files
📊 Grouped into 5 events
🎞  Total clips to process: 15

================================================================================
🚀 STAGE 3/5: TRANSCRIPTION & DIARIZATION
================================================================================

  📋 Queued: 20250101_120000_camera1 (3 clips)
  📋 Queued: 20250101_123000_camera1 (4 clips)
  ...

  ℹ️  Processing 5 groups (skipped 0 existing)
  Overall transcription progress ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 40%

^C  # User interrupts with Ctrl+C

  ⚠️  SIGINT received: cancelling transcription workers...
```

### Resumed Run (Continues from where it left off)
```bash
$ python main.py

🎬 BLINK VIDEO PROCESSING PIPELINE
================================================================================

📁 Existing output detected - pipeline will resume from where it left off
   (Already completed groups will be skipped)

📁 Found 15 video files
📊 Grouped into 5 events
🎞  Total clips to process: 15

================================================================================
🚀 STAGE 3/5: TRANSCRIPTION & DIARIZATION
================================================================================

  📋 Queued: 20250101_120000_camera1 (3 clips)
  📋 Queued: 20250101_123000_camera1 (4 clips)
  ...

  ℹ️  Skipping 20250101_120000_camera1 - transcript already exists
  ℹ️  Skipping 20250101_123000_camera1 - transcript already exists
  ℹ️  Processing 3 groups (skipped 2 existing)

  Overall transcription progress ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%

✅ Transcription & Diarization completed!
   Successfully processed: 5

...

================================================================================
🚀 STAGE 5/5: VIDEO MERGING
================================================================================

  ℹ️  Skipping 20250101_120000_camera1 - merged video already exists
  ℹ️  Skipping 20250101_123000_camera1 - merged video already exists
  ℹ️  Processing 3 groups (skipped 2 existing)

  Overall merge progress ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%

✅ Video Merging completed!
   Successfully processed: 5  # Includes 2 existing + 3 new
```

## Technical Details

### File Naming Convention
The resume functionality relies on consistent file naming:
- **Group name format**: `{YYYYMMDD_HHMMSS}_{camera_name}`
- **Transcript files**: `{group_name}_transcript.txt`
- **Merged videos**: `{group_name}_merged.mp4`

### Detection Logic
```python
# Stage 3: Check for existing transcripts
existing_transcripts = set()
if os.path.exists(transcripts_dir):
    existing_transcripts = {
        f.replace('_transcript.txt', '')
        for f in os.listdir(transcripts_dir)
        if f.endswith('_transcript.txt')
    }

# Stage 5: Check for existing merged videos
existing_videos = set()
if os.path.exists(group_outputs_dir):
    existing_videos = {
        f.replace('_merged.mp4', '')
        for f in os.listdir(group_outputs_dir)
        if f.endswith('_merged.mp4')
    }
```

### Skipping Logic
```python
for job in group_jobs:
    group_name = job[0]
    if group_name in existing_transcripts:
        progress.log_info(f"Skipping {group_name} - transcript already exists")
        # Still track paths for downstream stages
        stage3_results[group_name] = (video_paths, None)
        completed_count += 1
    else:
        jobs_to_process.append(job)
```

## Important Notes

### ✅ What IS Preserved
- **Transcript files** (`.txt` in `output/transcripts/`)
- **Merged videos** (`.mp4` in `output/merged_videos/`)
- **Speaker voice samples** (`.wav` in `output/speaker_voice_samples/`)
- **Repaired video cache** (in `output/repaired_cache/`)

### ❌ What IS NOT Preserved
- **In-memory state** (current processing progress within a group)
- **Partial transcripts** (if a group fails mid-processing, it will restart)
- **Partial merges** (if a merge fails, the group will be reprocessed)

### Interruption Handling
The pipeline handles interruptions gracefully:
1. **Ctrl+C (SIGINT)**: Caught by `KeyboardInterrupt` handlers
2. **Worker cancellation**: ProcessPoolExecutor workers are terminated
3. **State preservation**: Only completed groups (with output files) are considered done

### Re-running Completed Pipeline
If you re-run the pipeline on the same input after it has fully completed:
- All groups will be skipped
- Stages will show "Processing 0 groups (skipped N existing)"
- Pipeline completes almost instantly
- Summary still shows correct counts

### Forcing Full Re-processing
To force a complete re-run (ignore existing output):
```bash
# Delete output directories
rm -rf output/transcripts output/merged_videos output/speaker_voice_samples

# Or move them to a backup
mv output output_backup_$(date +%Y%m%d_%H%M%S)

# Then run the pipeline
python main.py
```

## Benefits

1. **Time Saving**: Don't re-process groups that succeeded before interruption
2. **Cost Saving**: Avoid redundant Whisper API calls or GPU processing
3. **Reliability**: Safe to interrupt and resume at any time
4. **Transparency**: Clear logging shows what's being skipped vs. processed
5. **Idempotent**: Running the same pipeline multiple times produces the same output

## Limitations

### Partial Group Processing
If a group is interrupted mid-transcription:
- The transcript file won't exist yet
- On resume, the group will be fully reprocessed (not continued)
- This is by design - ensures data consistency

### Changed Input Files
If input files change between runs:
- File discovery runs fresh each time
- Groups are re-determined based on current files
- Existing output may not match new grouping
- **Recommendation**: Don't modify input files between resume runs

### Stage 4 Dependency
- Stage 4 (Speaker ID) has no separate resume logic
- It depends on diarization results from Stage 3
- If transcript exists, speaker ID was already done
- This is safe because transcripts include speaker names

## Testing Resume Functionality

To test the resume feature:

1. **Start a run**:
   ```bash
   python main.py
   ```

2. **Interrupt with Ctrl+C** during Stage 3 or 5

3. **Check output directory**:
   ```bash
   ls output/transcripts/
   ls output/merged_videos/
   ```

4. **Resume**:
   ```bash
   python main.py
   ```

5. **Verify**: Pipeline should skip groups with existing output

## Troubleshooting

### Issue: Pipeline not detecting existing output
**Possible causes**:
- Output directory path changed in config.yaml
- File naming pattern doesn't match
- File permissions preventing directory listing

**Solution**:
- Check config.yaml paths match actual output locations
- Verify file naming follows `{group_name}_transcript.txt` pattern
- Check file permissions on output directories

### Issue: Groups being reprocessed despite existing output
**Possible causes**:
- Group name generation changed (datetime format or camera name)
- Input files moved/renamed causing different grouping
- Transcript/video files manually renamed

**Solution**:
- Ensure input files haven't changed
- Check that group names in output match current naming pattern
- Verify config.yaml hasn't changed grouping parameters

### Issue: Pipeline skips everything but output is incomplete
**Possible causes**:
- Output files exist but are corrupt/empty
- Previous run had failures but created empty files

**Solution**:
- Check file sizes: `ls -lh output/transcripts/`
- Manually delete incomplete files
- Re-run pipeline

## Summary

The resume functionality makes the Blink pipeline robust and production-ready:
- ✅ Automatically detects completed work
- ✅ Skips already-processed groups
- ✅ Handles interruptions gracefully
- ✅ Provides clear user feedback
- ✅ Maintains data consistency
- ✅ Works with concurrent processing

Simply run `python main.py` - the pipeline will always do the right thing!
