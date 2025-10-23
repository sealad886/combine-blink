#!/usr/bin/env python3
"""
Test substage timing feature.

This test demonstrates that substage elapsed time only starts counting
when work actually begins on that substage (first progress update),
not when the substage is added to the queue.
"""

import time
from blink_pipeline.pipeline_dashboard import PipelineDashboard

def simulate_queued_processing():
    """Simulate concurrent processing where substages queue up."""
    dashboard = PipelineDashboard(
        total_videos=10,
        total_groups=5,
        total_clips=20
    )

    with dashboard:
        # Start transcription stage with 3 groups
        dashboard.start_stage('transcription', 3)

        # Add all 3 groups to the queue immediately
        print("\n⏱️  Adding all groups to queue (timers should NOT start yet)...")
        dashboard.add_substage('transcription', 'Group_A_3clips', 3)
        dashboard.add_substage('transcription', 'Group_B_5clips', 5)
        dashboard.add_substage('transcription', 'Group_C_2clips', 2)
        time.sleep(2)  # 2 seconds with no work

        print("\n▶️  Starting work on Group_A (timer should start now)...")
        for i in range(1, 4):
            dashboard.update_substage('transcription', 'Group_A_3clips', i)
            time.sleep(1)  # 1 second per clip
        dashboard.remove_substage('transcription', 'Group_A_3clips')

        print("\n▶️  Starting work on Group_B (timer should start now)...")
        # Note: Group_B was added 5+ seconds ago, but timer starts NOW
        for i in range(1, 6):
            dashboard.update_substage('transcription', 'Group_B_5clips', i)
            time.sleep(0.8)  # 0.8 seconds per clip
        dashboard.remove_substage('transcription', 'Group_B_5clips')

        print("\n▶️  Starting work on Group_C (timer should start now)...")
        # Note: Group_C was added 9+ seconds ago, but timer starts NOW
        for i in range(1, 3):
            dashboard.update_substage('transcription', 'Group_C_2clips', i)
            time.sleep(1)  # 1 second per clip
        dashboard.remove_substage('transcription', 'Group_C_2clips')

        dashboard.complete_stage('transcription', "3 groups processed")

        print("\n✅ Test complete!")
        print("\nExpected behavior:")
        print("  • Group_A should show ~3s elapsed (3 clips × 1s)")
        print("  • Group_B should show ~4s elapsed (5 clips × 0.8s)")
        print("  • Group_C should show ~2s elapsed (2 clips × 1s)")
        print("\nNOTE: Queue time (2s before work began) should NOT be counted!")

if __name__ == '__main__':
    simulate_queued_processing()
