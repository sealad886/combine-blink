"""
Enhanced test script for Pipeline Dashboard with visible ETA.

This script runs slower to make ETA calculations visible during execution.
"""

import time
from src.pipeline_dashboard import PipelineDashboard

def main():
    """Test the pipeline dashboard with visible ETA calculations."""
    print("Testing Pipeline Dashboard with ETA Display...")
    print("=" * 80)
    print("Running slower simulation to see ETA calculations in action...")
    print()

    # Create dashboard
    dashboard = PipelineDashboard(
        total_videos=50,
        total_groups=10,
        total_clips=50
    )

    with dashboard:
        # Stage 1: Validation (slower to see ETA)
        dashboard.start_stage('validation', 50)
        for i in range(50):
            time.sleep(0.2)  # Slower to make ETA visible
            dashboard.update_stage('validation', i + 1, f"Processing video {i + 1}")
        dashboard.complete_stage('validation', "15 repaired, 35 original")

        time.sleep(1)

        # Stage 2: Transcription with substages
        dashboard.start_stage('transcription', 10)
        groups = [f'event_{i:02d}_{1000+i}' for i in range(10)]

        for i, group in enumerate(groups):
            dashboard.add_substage('transcription', group, 5)

            # Simulate processing clips in each group
            for clip in range(5):
                time.sleep(0.15)
                dashboard.update_substage('transcription', group, clip + 1)

            dashboard.remove_substage('transcription', group)
            dashboard.update_stage('transcription', i + 1, f"Completed {i + 1}/10 groups")

        dashboard.complete_stage('transcription', "10 groups processed")

        time.sleep(1)

        # Stage 3: Speaker ID
        dashboard.start_stage('speaker_id', 10)
        for i in range(10):
            time.sleep(0.3)
            dashboard.update_stage('speaker_id', i + 1, f"Identifying speakers in group {i + 1}")
        dashboard.complete_stage('speaker_id', "10 groups processed")

        time.sleep(1)

        # Stage 4: Merge with substages - simulate different clip counts per group
        dashboard.start_stage('merge', 10)
        clip_counts = [3, 2, 4, 1, 5, 2, 3, 4, 2, 3]  # Different numbers of clips per group
        for i, (group, num_clips) in enumerate(zip(groups, clip_counts)):
            dashboard.add_substage('merge', group, num_clips)

            # Simulate merging clips one by one
            for clip in range(num_clips):
                time.sleep(0.2)
                dashboard.update_substage('merge', group, clip + 1)

            dashboard.remove_substage('merge', group)
            dashboard.update_stage('merge', i + 1, f"Merged {i + 1}/10 events")
        dashboard.complete_stage('merge', "10 groups merged")

    # Final summary is printed when context manager exits
    dashboard.print_summary()

    print("\n" + "=" * 80)
    print("Dashboard test complete!")
    print("Notice how ETA appeared in:")
    print("  • Header (overall pipeline ETA)")
    print("  • Stage table 'Time' column (per-stage ETA)")
    print("  • Current stage panel title (active stage ETA)")

if __name__ == '__main__':
    main()
