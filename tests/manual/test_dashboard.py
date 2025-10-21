"""
Test script for the Pipeline Dashboard.

This script simulates the pipeline stages to verify the dashboard display works correctly.
"""

import time
from src.pipeline_dashboard import PipelineDashboard

def main():
    """Test the pipeline dashboard with simulated work."""
    print("Testing Pipeline Dashboard...")
    print("=" * 80)

    # Create dashboard
    dashboard = PipelineDashboard(
        total_videos=20,
        total_groups=5,
        total_clips=20
    )

    with dashboard:
        # Stage 1: Validation
        dashboard.start_stage('validation', 20)
        for i in range(20):
            time.sleep(0.1)
            dashboard.update_stage('validation', i + 1, f"{i + 1}/20 videos")
        dashboard.complete_stage('validation', "5 repaired, 15 original")

        time.sleep(0.5)

        # Stage 2: Transcription
        dashboard.start_stage('transcription', 5)
        groups = ['group_1', 'group_2', 'group_3', 'group_4', 'group_5']

        for i, group in enumerate(groups):
            dashboard.add_substage('transcription', group, 4)

            # Simulate processing clips in each group
            for clip in range(4):
                time.sleep(0.1)
                dashboard.update_substage('transcription', group, clip + 1)

            dashboard.remove_substage('transcription', group)
            dashboard.update_stage('transcription', i + 1, f"{i + 1}/5 groups")

        dashboard.complete_stage('transcription', "5 groups processed")

        time.sleep(0.5)

        # Stage 3: Speaker ID
        dashboard.start_stage('speaker_id', 5)
        for i in range(5):
            time.sleep(0.2)
            dashboard.update_stage('speaker_id', i + 1, f"Processed: group_{i + 1}")
        dashboard.complete_stage('speaker_id', "5 groups processed")

        time.sleep(0.5)

        # Stage 4: Merge
        dashboard.start_stage('merge', 5)
        for i, group in enumerate(groups):
            dashboard.add_substage('merge', group, 1)
            time.sleep(0.3)
            dashboard.update_substage('merge', group, 1)
            dashboard.remove_substage('merge', group)
            dashboard.update_stage('merge', i + 1, f"Merging {i + 1}/5 groups")
        dashboard.complete_stage('merge', "5 groups merged")

    # Final summary is printed when context manager exits
    dashboard.print_summary()

    print("\n" + "=" * 80)
    print("Dashboard test complete!")

if __name__ == '__main__':
    main()
