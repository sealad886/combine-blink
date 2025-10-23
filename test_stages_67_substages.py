#!/usr/bin/env python3
"""Test to verify substages display correctly for stages 6 and 7."""

import time
from blink_pipeline.pipeline_dashboard import PipelineDashboard

# Create dashboard with realistic numbers
dashboard = PipelineDashboard(
    total_videos=726,
    total_groups=14,
    total_clips=726
)

with dashboard:
    # Skip earlier stages to focus on 6 and 7
    dashboard.skip_stage('validation', 'Already completed')
    dashboard.skip_stage('transcription', 'Already completed')
    dashboard.skip_stage('speaker_id', 'Already completed')
    dashboard.skip_stage('merge', 'Already completed')

    print("\n" + "="*80)
    print("Testing Stage 6: Final Video Transcription with substages")
    print("="*80 + "\n")

    # Simulate Stage 6: Final Transcription with 3 groups
    merged_videos = [
        ('20251015_083743_Corner+Entry+Frontdoor', 'output/merged_videos/20251015_083743_Corner+Entry+Frontdoor_merged.mp4'),
        ('20251015_110921_Entry+Frontdoor', 'output/merged_videos/20251015_110921_Entry+Frontdoor_merged.mp4'),
        ('20251015_135502_Corner+Entry+Frontdoor', 'output/merged_videos/20251015_135502_Corner+Entry+Frontdoor_merged.mp4'),
    ]

    dashboard.start_stage('final_transcription', len(merged_videos))
    time.sleep(1)

    for idx, (group_name, _) in enumerate(merged_videos, 1):
        print(f"Processing group {idx}/{len(merged_videos)}: {group_name}")

        # Add substage (3 steps: load metadata, transcribe, write)
        dashboard.add_substage('final_transcription', group_name, 3)
        time.sleep(0.5)

        # Step 1: Load metadata
        print(f"  Step 1/3: Loading metadata...")
        dashboard.update_substage('final_transcription', group_name, 1)
        time.sleep(1.5)

        # Step 2: Transcribe (this would take longest in reality)
        print(f"  Step 2/3: Transcribing...")
        dashboard.update_substage('final_transcription', group_name, 2)
        time.sleep(2.0)

        # Step 3: Write transcript
        print(f"  Step 3/3: Writing transcript...")
        dashboard.update_substage('final_transcription', group_name, 3)
        dashboard.update_stage('final_transcription', idx, f"Done: {group_name}")
        time.sleep(0.5)

        # Remove substage when done
        dashboard.remove_substage('final_transcription', group_name)
        print(f"  ✓ Completed: {group_name}\n")
        time.sleep(0.5)

    dashboard.complete_stage('final_transcription', f'{len(merged_videos)} videos transcribed')
    print("\n✓ Stage 6 complete!")
    time.sleep(2)

    print("\n" + "="*80)
    print("Testing Stage 7: Speaker Profiles Export with substage")
    print("="*80 + "\n")

    # Simulate Stage 7: Speaker Profiles
    dashboard.start_stage('speaker_profiles', 1)
    time.sleep(0.5)

    print("Exporting speaker profiles...")
    dashboard.add_substage('speaker_profiles', 'profiles.json', 1)
    time.sleep(1.5)

    print("  Collecting speaker data...")
    time.sleep(1.0)

    print("  Writing profiles.json...")
    dashboard.update_substage('speaker_profiles', 'profiles.json', 1)
    dashboard.update_stage('speaker_profiles', 1, '5 speakers')
    time.sleep(1.0)

    dashboard.remove_substage('speaker_profiles', 'profiles.json')
    dashboard.complete_stage('speaker_profiles', 'Profiles exported')
    print("✓ Stage 7 complete!\n")
    time.sleep(2)

    print("\n" + "="*80)
    print("Final dashboard state (holding for 3 seconds)...")
    print("="*80 + "\n")
    time.sleep(3)

print("\n" + "="*80)
dashboard.print_summary()
print("="*80)
print("\n✓ Dashboard substage test complete!")
print("\nThe right-most panel should have shown:")
print("  - For Stage 6: Individual groups with progress bars (0/3 → 3/3)")
print("  - For Stage 7: profiles.json with progress (0/1 → 1/1)")
print("  - Real-time timing information for each substage")
