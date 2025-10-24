#!/usr/bin/env python3
"""
Test to verify substage timing displays correctly.

This test keeps substages in a running state long enough to see
the elapsed time column in action.
"""

import time
from blink_pipeline.pipeline_dashboard import PipelineDashboard

def test_substage_timing_display():
    """Test that substage elapsed times are displayed correctly."""
    dashboard = PipelineDashboard(
        total_videos=10,
        total_groups=4,
        total_clips=15
    )

    with dashboard:
        dashboard.start_stage('transcription', 4)

        # Add 4 groups
        print("\n📝 Adding groups to queue (no timers yet)...")
        dashboard.add_substage('transcription', 'Meeting_Room_5clips', 5)
        dashboard.add_substage('transcription', 'Front_Door_3clips', 3)
        dashboard.add_substage('transcription', 'Back_Yard_4clips', 4)
        dashboard.add_substage('transcription', 'Garage_3clips', 3)

        time.sleep(2)  # Queue time - timers should NOT count this

        # Start work on each group with delays to show timing
        print("\n▶️  Starting Group 1 (Meeting Room)...")
        dashboard.update_substage('transcription', 'Meeting_Room_5clips', 1)
        time.sleep(2)  # Let timer run

        print("▶️  Starting Group 2 (Front Door)...")
        dashboard.update_substage('transcription', 'Front_Door_3clips', 1)
        time.sleep(1)

        print("▶️  Starting Group 3 (Back Yard)...")
        dashboard.update_substage('transcription', 'Back_Yard_4clips', 1)
        time.sleep(1)

        print("▶️  Starting Group 4 (Garage)...")
        dashboard.update_substage('transcription', 'Garage_3clips', 1)
        time.sleep(1)

        # Now update all groups while keeping them visible
        print("\n⏱️  All groups now processing (check elapsed times)...\n")

        for i in range(5):
            # Update various groups
            if i < 5:
                dashboard.update_substage('transcription', 'Meeting_Room_5clips', min(i + 2, 5))
            if i < 3:
                dashboard.update_substage('transcription', 'Front_Door_3clips', min(i + 2, 3))
            if i < 4:
                dashboard.update_substage('transcription', 'Back_Yard_4clips', min(i + 2, 4))
            if i < 3:
                dashboard.update_substage('transcription', 'Garage_3clips', min(i + 2, 3))

            time.sleep(1)  # Update every second

        print("\n✅ Check the dashboard above:")
        print("   • Meeting Room should show ~9s (started first)")
        print("   • Front Door should show ~7s (started 2s after)")
        print("   • Back Yard should show ~6s (started 3s after)")
        print("   • Garage should show ~5s (started 4s after)")
        print("\n   Queue time (initial 2s) should NOT be counted!\n")

        # Keep display visible
        time.sleep(3)

        dashboard.complete_stage('transcription', "4 groups done")

if __name__ == '__main__':
    test_substage_timing_display()
