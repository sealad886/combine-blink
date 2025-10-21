import os
import random
from src.media_utils import repair_video, probe_media_info
import logging

logging.basicConfig(level=logging.INFO)

# Scan for all .mp4 files in input directory
INPUT_DIR = '25-10-15'
CACHE_DIR = 'output/repaired_cache'  # Use unified repair cache
OUTPUT_DIR = 'output/test_repairs'   # Separate test output directory
SAMPLE_SIZE = 30  # Large enough to get a few damaged files
DAMAGED_FILES = []
RESULTS = []

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Gather all .mp4 files
all_files = [os.path.join(INPUT_DIR, f) for f in os.listdir(INPUT_DIR) if f.endswith('.mp4')]
random.shuffle(all_files)

# Probe for damage (audio/video duration mismatch > 0.1s)
for clip in all_files[:SAMPLE_SIZE]:
    info = probe_media_info(clip)
    duration_diff = abs(info.video_duration - info.audio_duration)
    if info.has_audio and duration_diff > 0.1:
        DAMAGED_FILES.append(clip)
    if len(DAMAGED_FILES) >= 2:
        break

if not DAMAGED_FILES:
    print("No damaged files found in sample. Try increasing SAMPLE_SIZE or check input directory.")
else:
    print(f"Found {len(DAMAGED_FILES)} damaged files:")
    for f in DAMAGED_FILES:
        print(f"  {f}")

    for clip in DAMAGED_FILES:
        print(f"\n=== Testing {clip} ===")
        for strategy in ['fill', 'remove_blank']:
            out_path = os.path.join(OUTPUT_DIR, f"{os.path.basename(clip).replace('.mp4', '')}_{strategy}.mp4")
            print(f"  → Repairing with strategy: {strategy}")
            success = repair_video(clip, out_path, cache_dir=CACHE_DIR, strategy=strategy)
            if not success:
                print(f"    ✗ Repair failed for {strategy}")
                continue
            info = probe_media_info(out_path)
            print(f"    ✓ Output: {out_path}")
            print(f"      Video duration: {info.video_duration:.2f}s, Audio duration: {info.audio_duration:.2f}s, Has audio: {info.has_audio}")
            RESULTS.append({
                'clip': clip,
                'strategy': strategy,
                'output': out_path,
                'video_duration': info.video_duration,
                'audio_duration': info.audio_duration,
                'has_audio': info.has_audio
            })

    print("\n=== Summary ===")
    for r in RESULTS:
        print(f"{r['clip']} | {r['strategy']} | video: {r['video_duration']:.2f}s | audio: {r['audio_duration']:.2f}s | audio present: {r['has_audio']}")
