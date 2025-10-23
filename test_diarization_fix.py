#!/usr/bin/env python3
"""Test script to verify diarization fix works."""

import sys
import logging
from pathlib import Path
from blink_pipeline.transcription import process_audio_for_transcription
import yaml

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s')

# Load config
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

# Test with a small set of clips
test_clips = [
    "output/repaired_cache/repaired_fill_08-37-43_CornerG8T1K0013255014P_081_bc228a70.mp4",
    "output/repaired_cache/repaired_fill_08-37-55_EntryG8T1K0013255014H_080_1a514d57.mp4",
]

print("Testing diarization with 2 clips...")
print(f"Clips: {test_clips}")
print()

try:
    result = process_audio_for_transcription(test_clips, config)

    if result:
        print("✓ SUCCESS: Diarization completed!")
        print(f"  Segments: {len(result.get('segments', []))}")
        print(f"  Timeline entries: {len(result.get('timeline', []))}")

        # Show first few segments
        segments = result.get('segments', [])
        print("\nFirst 3 segments:")
        for seg in segments[:3]:
            print(f"  [{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['speaker']}: {seg['text'][:50]}")
    else:
        print("✗ FAILED: No result returned (likely no speech detected)")
        sys.exit(1)

except Exception as e:
    print(f"✗ FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
