#!/usr/bin/env python3
"""Test script to verify dashboard substage display for stages 6 and 7."""

import time
from blink_pipeline.pipeline_dashboard import PipelineDashboard

# Create dashboard
dashboard = PipelineDashboard(
    total_videos=10,
    total_groups=3,
    total_clips=30
)

with dashboard:
    # Simulate Stage 6: Final Transcription
    print("Testing Stage 6: Final Transcription with substages...")
    dashboard.start_stage('final_transcription', 3)
    time.sleep(1)

    # Group 1
    dashboard.add_substage('final_transcription', '20251015_083743_Corner+Entry', 1)
    time.sleep(0.5)
    dashboard.update_substage('final_transcription', '20251015_083743_Corner+Entry', 1)
    dashboard.update_stage('final_transcription', 1)
    time.sleep(0.5)
    dashboard.remove_substage('final_transcription', '20251015_083743_Corner+Entry')

    # Group 2
    dashboard.add_substage('final_transcription', '20251015_110921_Entry+Frontdoor', 1)
    time.sleep(0.5)
    dashboard.update_substage('final_transcription', '20251015_110921_Entry+Frontdoor', 1)
    dashboard.update_stage('final_transcription', 2)
    time.sleep(0.5)
    dashboard.remove_substage('final_transcription', '20251015_110921_Entry+Frontdoor')

    # Group 3
    dashboard.add_substage('final_transcription', '20251015_135502_Corner+Entry', 1)
    time.sleep(0.5)
    dashboard.update_substage('final_transcription', '20251015_135502_Corner+Entry', 1)
    dashboard.update_stage('final_transcription', 3)
    time.sleep(0.5)
    dashboard.remove_substage('final_transcription', '20251015_135502_Corner+Entry')

    dashboard.complete_stage('final_transcription', '3 videos transcribed')
    time.sleep(1)

    # Simulate Stage 7: Speaker Profiles
    print("Testing Stage 7: Speaker Profiles with substage...")
    dashboard.start_stage('speaker_profiles', 1)
    time.sleep(0.5)
    dashboard.add_substage('speaker_profiles', 'profiles.json', 1)
    time.sleep(0.5)
    dashboard.update_substage('speaker_profiles', 'profiles.json', 1)
    dashboard.update_stage('speaker_profiles', 1, '5 speakers')
    time.sleep(0.5)
    dashboard.remove_substage('speaker_profiles', 'profiles.json')
    dashboard.complete_stage('speaker_profiles', 'Profiles exported')
    time.sleep(1)

dashboard.print_summary()
print("\n✓ Dashboard substage test complete!")
