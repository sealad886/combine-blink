import os
from src.media_utils import repair_video, probe_media_info
import logging

logging.basicConfig(level=logging.INFO)

# List of sample Blink clips to test (update with your actual files)
SAMPLE_CLIPS = [
    '25-10-15/sample1.mp4',
    '25-10-15/sample2.mp4',
    '25-10-15/sample3.mp4',
]

CACHE_DIR = 'output/repaired_cache'  # Use unified repair cache
OUTPUT_DIR = 'output/test_repairs'   # Separate test output directory
RESULTS = []

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

for clip in SAMPLE_CLIPS:
    if not os.path.exists(clip):
        print(f"✗ File not found: {clip}")
        continue
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
