#!/usr/bin/env python3
"""Quick test of Stage 6 transcript formatting on one video."""

import yaml
import os
from pathlib import Path
from datetime import datetime, timedelta
from blink_pipeline.transcription import process_audio_for_transcription
from blink_pipeline.identify_speaker import SpeakerIdentifier

# Load config
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Find one merged video
merged_dir = "output/merged_videos"
video_files = [f for f in os.listdir(merged_dir) if f.endswith('_merged.mp4') and os.path.getsize(os.path.join(merged_dir, f)) > 0]
if not video_files:
    print("No merged videos found")
    exit(1)

# Use the first one
video_file = video_files[0]
video_path = os.path.join(merged_dir, video_file)
group_name = video_file[:-len('_merged.mp4')]

print(f"Testing with: {group_name}")
print(f"Video path: {video_path}")

# Extract start time from group_name
video_start_time = None
try:
    parts = group_name.split('_')
    if len(parts) >= 2:
        date_str = parts[0]  # YYYYMMDD
        time_str = parts[1]  # HHMMSS
        video_start_time = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
        print(f"Parsed start time: {video_start_time}")
except Exception as e:
    print(f"Could not parse timestamp: {e}")

# Run transcription (just first 30 seconds to be fast)
print("\nRunning transcription...")
diarization_result = process_audio_for_transcription([video_path], config)

if not diarization_result or not diarization_result.get('segments'):
    print("No segments found")
    exit(1)

segments = diarization_result['segments']
print(f"Found {len(segments)} segments")

# Format like a script
lines = []
lines.append(f"=== TRANSCRIPT: {group_name} ===")
if video_start_time:
    lines.append(f"Recording started: {video_start_time.strftime('%B %d, %Y at %I:%M:%S %p')}")
lines.append("")

for entry in segments[:10]:  # Just first 10 segments
    spk = entry.get('speaker', 'Unknown')
    text = entry.get('text', '')
    start_seconds = entry.get('start', 0.0)

    # Calculate wall-clock time
    timestamp_str = ""
    if video_start_time:
        actual_time = video_start_time + timedelta(seconds=start_seconds)
        timestamp_str = actual_time.strftime("%I:%M:%S %p")
    else:
        mins = int(start_seconds // 60)
        secs = int(start_seconds % 60)
        timestamp_str = f"+{mins:02d}:{secs:02d}"

    lines.append(f"[{timestamp_str}] {spk}: {text}")

print("\n--- FORMATTED TRANSCRIPT ---")
print("\n".join(lines))
