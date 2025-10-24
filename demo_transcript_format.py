#!/usr/bin/env python3
"""Demo of the new transcript format."""

from datetime import datetime, timedelta

# Simulate transcript data
group_name = "20251015_215513_Entry+Frontdoor"
video_start_time = datetime.strptime("20251015_215513", "%Y%m%d_%H%M%S")

# Sample segments (simulated diarization output)
segments = [
    {"start": 0.0, "end": 4.2, "speaker": "SPEAKER_00", "text": "Oh, there it is."},
    {"start": 4.5, "end": 8.3, "speaker": "SPEAKER_01", "text": "And so we're going to go with six worth to take it off the top."},
    {"start": 9.1, "end": 12.5, "speaker": "SPEAKER_00", "text": "And if it's too long with Danny, he was like 12."},
    {"start": 13.0, "end": 16.8, "speaker": "SPEAKER_01", "text": "And so I was very sad and he was going to work."},
    {"start": 17.2, "end": 20.5, "speaker": "SPEAKER_00", "text": "And like numbers called all of them? Yeah."},
]

# Format transcript
lines = []
lines.append(f"=== TRANSCRIPT: {group_name} ===")
lines.append(f"Recording started: {video_start_time.strftime('%B %d, %Y at %I:%M:%S %p')}")
lines.append("")

for entry in segments:
    spk = entry.get('speaker', 'Unknown')
    text = entry.get('text', '')
    start_seconds = entry.get('start', 0.0)

    # Calculate wall-clock time
    actual_time = video_start_time + timedelta(seconds=start_seconds)
    timestamp_str = actual_time.strftime("%I:%M:%S %p")

    lines.append(f"[{timestamp_str}] {spk}: {text}")

print("\n".join(lines))
print("\n--- This is what the new transcript format looks like ---")
