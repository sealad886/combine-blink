#!/usr/bin/env python3
"""Visual test to see dashboard substage display for stages 6 and 7."""

import time
from blink_pipeline.pipeline_dashboard import PipelineDashboard

# Create dashboard
dashboard = PipelineDashboard(
    total_videos=10,
    total_groups=3,
    total_clips=30
)

with dashboard:
    # Skip earlier stages
    dashboard.skip_stage('validation', 'Skipped for test')
    dashboard.skip_stage('transcription', 'Skipped for test')
    dashboard.skip_stage('speaker_id', 'Skipped for test')
    dashboard.skip_stage('merge', 'Skipped for test')

    # Simulate Stage 6: Final Transcription with visible substages
    print("Starting Stage 6: Final Transcription...")
    dashboard.start_stage('final_transcription', 3)
    time.sleep(1)

    # Group 1 - show in progress
    dashboard.add_substage('final_transcription', '20251015_083743_Corner+Entry', 1)
    time.sleep(2)  # Keep visible for 2 seconds
    dashboard.update_substage('final_transcription', '20251015_083743_Corner+Entry', 1)
    dashboard.update_stage('final_transcription', 1)
    time.sleep(1)
    dashboard.remove_substage('final_transcription', '20251015_083743_Corner+Entry')

    # Group 2 - show in progress
    dashboard.add_substage('final_transcription', '20251015_110921_Entry+Frontdoor', 1)
    time.sleep(2)  # Keep visible
    dashboard.update_substage('final_transcription', '20251015_110921_Entry+Frontdoor', 1)
    dashboard.update_stage('final_transcription', 2)
    time.sleep(1)
    dashboard.remove_substage('final_transcription', '20251015_110921_Entry+Frontdoor')

    # Group 3 - show in progress
    dashboard.add_substage('final_transcription', '20251015_135502_Corner+Entry', 1)
    time.sleep(2)  # Keep visible
    dashboard.update_substage('final_transcription', '20251015_135502_Corner+Entry', 1)
    dashboard.update_stage('final_transcription', 3)
    time.sleep(1)
    dashboard.remove_substage('final_transcription', '20251015_135502_Corner+Entry')

    dashboard.complete_stage('final_transcription', '3 videos transcribed')
    time.sleep(2)

    # Simulate Stage 7: Speaker Profiles
    print("Starting Stage 7: Speaker Profiles...")
    dashboard.start_stage('speaker_profiles', 1)
    time.sleep(1)
    dashboard.add_substage('speaker_profiles', 'profiles.json', 1)
    time.sleep(2)  # Keep visible
    dashboard.update_substage('speaker_profiles', 'profiles.json', 1)
    dashboard.update_stage('speaker_profiles', 1, '5 speakers')
    time.sleep(1)
    dashboard.remove_substage('speaker_profiles', 'profiles.json')
    dashboard.complete_stage('speaker_profiles', 'Profiles exported')
    time.sleep(2)

    print("\nHolding dashboard for 3 seconds to view final state...")
    time.sleep(3)

dashboard.print_summary()
print("\n✓ Visual dashboard test complete!")
