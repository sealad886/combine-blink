# Dashboard Substage Implementation for Stages 6 & 7

## Summary

Enhanced the pipeline dashboard to properly display substage progress for the newly added Stages 6 and 7.

## Changes Made

### Stage 6: Final Video Transcription (`orchestrator.py`)

**Location:** Lines ~895-1020

**Substage Tracking:**
- Each merged video is tracked as a substage with 3 steps:
  1. **Load metadata** - Parse video start time from filename
  2. **Transcribe** - Run whisper.cpp with diarization
  3. **Write transcript** - Format and save final transcript file

**Implementation:**
```python
# Before processing each group
dashboard.add_substage('final_transcription', group_name, 3)

# Step 1: Load metadata
dashboard.update_substage('final_transcription', group_name, 1)

# Step 2: Transcribe (inside try/except)
dashboard.update_substage('final_transcription', group_name, 2)

# Step 3: Write (after file write)
dashboard.update_substage('final_transcription', group_name, 3)
dashboard.update_stage('final_transcription', ft_completed, f"Done: {group_name}")
dashboard.remove_substage('final_transcription', group_name)
```

**Skip case handling:**
For videos that already have transcripts:
```python
if os.path.exists(out_txt):
    ft_completed += 1
    dashboard.update_substage('final_transcription', group_name, 3)  # Mark complete
    dashboard.update_stage('final_transcription', ft_completed, f"Skip (exists): {group_name}")
    dashboard.remove_substage('final_transcription', group_name)
    continue
```

### Stage 7: Speaker Profiles Export (`orchestrator.py`)

**Location:** Lines ~1024-1031

**Substage Tracking:**
- Single substage: `profiles.json` with 1 step (export)

**Implementation:**
```python
dashboard.start_stage('speaker_profiles', 1)
dashboard.add_substage('speaker_profiles', 'profiles.json', 1)
spk_count, prof_path = _write_speaker_profiles(config)
dashboard.update_substage('speaker_profiles', 'profiles.json', 1)
dashboard.update_stage('speaker_profiles', 1, f"{spk_count} speakers")
dashboard.remove_substage('speaker_profiles', 'profiles.json')
dashboard.complete_stage('speaker_profiles', f"Profiles at {prof_path}")
```

## Dashboard Display

The right-most panel now shows:

### For Stage 6 (Final Video Transcription):
```
Final Video Transcription • ETA: 0:05:30

20251015_083743_Corner+Entry  ██████████ 2/3       15s
20251015_110921_Entry+Front   ████░░░░░░ 1/3       8s
20251015_135502_Corner+Entry  ░░░░░░░░░░ 0/3       —
...
```

### For Stage 7 (Speaker Profiles Export):
```
Speaker Profiles Export - 5 speakers

profiles.json              ██████████ 1/1       2s
```

## Benefits

1. **Real-time visibility** - Users can see which specific group is being processed
2. **Progress granularity** - Within each group, users see multi-step progress (load → transcribe → write)
3. **Timing information** - Each substage displays elapsed time
4. **Consistency** - Matches the pattern used in Stages 3 (transcription) and 5 (merge)
5. **Professional UX** - Clear, informative dashboard that shows meaningful progress

## Testing

Created comprehensive test: `test_stages_67_substages.py`
- Simulates 3 groups for Stage 6
- Shows step-by-step progress (1/3, 2/3, 3/3)
- Simulates Stage 7 with profiles.json export
- Verifies timing information is displayed correctly
- Confirms substages are properly removed after completion

## Verification

Run the test:
```bash
python test_stages_67_substages.py
```

Expected output:
- ✓ Stage 6 shows individual groups with progress bars
- ✓ Stage 7 shows profiles.json export
- ✓ Real-time timing for each substage
- ✓ Clean completion summary with durations
