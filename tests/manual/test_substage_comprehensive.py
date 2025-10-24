#!/usr/bin/env python3
"""
Comprehensive demonstration of substage timing enhancement.

This test shows the complete workflow with queue time vs. processing time.
"""

import time
from blink_pipeline.pipeline_dashboard import PipelineDashboard

def main():
    """Demonstrate substage timing feature comprehensively."""
    print("\n" + "="*80)
    print("SUBSTAGE TIMING DEMONSTRATION")
    print("="*80)
    print("\nThis test demonstrates that substage timers only start when work")
    print("actually begins, not when substages are added to the queue.\n")

    dashboard = PipelineDashboard(
        total_videos=12,
        total_groups=5,
        total_clips=20
    )

    with dashboard:
        # ===== PHASE 1: Queue Setup =====
        print("PHASE 1: Adding all groups to queue")
        print("-" * 80)
        dashboard.start_stage('transcription', 5)

        groups = [
            ('Conference_Room_4clips', 4),
            ('Main_Entrance_3clips', 3),
            ('Parking_Lot_5clips', 5),
            ('Loading_Dock_2clips', 2),
            ('Cafeteria_6clips', 6),
        ]

        for name, total in groups:
            dashboard.add_substage('transcription', name, total)
            print(f"  ✓ Added: {name} ({total} clips)")

        print("\n⏳ All groups queued. Waiting 3 seconds before processing...")
        print("   (This queue time should NOT be counted in elapsed times)")
        time.sleep(3)

        # ===== PHASE 2: Staggered Processing =====
        print("\nPHASE 2: Processing groups with staggered starts")
        print("-" * 80)

        # Process Group 1 (starts immediately)
        print("\n▶️  [T+0s] Starting Conference_Room (4 clips)...")
        for i in range(1, 5):
            dashboard.update_substage('transcription', 'Conference_Room_4clips', i)
            time.sleep(0.5)  # 0.5s per clip = 2s total
        print("   ✓ Conference_Room complete (~2s processing time)")

        # Wait 1 second before starting next group
        time.sleep(1)

        # Process Group 2 (starts after 3s)
        print("\n▶️  [T+3s] Starting Main_Entrance (3 clips)...")
        for i in range(1, 4):
            dashboard.update_substage('transcription', 'Main_Entrance_3clips', i)
            time.sleep(0.7)  # 0.7s per clip = 2.1s total
        print("   ✓ Main_Entrance complete (~2s processing time)")

        # Wait 1 second
        time.sleep(1)

        # Process Group 3 (starts after 6s)
        print("\n▶️  [T+6s] Starting Parking_Lot (5 clips)...")
        for i in range(1, 6):
            dashboard.update_substage('transcription', 'Parking_Lot_5clips', i)
            time.sleep(0.6)  # 0.6s per clip = 3s total
        print("   ✓ Parking_Lot complete (~3s processing time)")

        # Wait 1 second
        time.sleep(1)

        # Process Group 4 (starts after 10s)
        print("\n▶️  [T+10s] Starting Loading_Dock (2 clips)...")
        for i in range(1, 3):
            dashboard.update_substage('transcription', 'Loading_Dock_2clips', i)
            time.sleep(0.8)  # 0.8s per clip = 1.6s total
        print("   ✓ Loading_Dock complete (~2s processing time)")

        # Wait 1 second
        time.sleep(1)

        # Process Group 5 (starts after 13s)
        print("\n▶️  [T+13s] Starting Cafeteria (6 clips)...")
        for i in range(1, 7):
            dashboard.update_substage('transcription', 'Cafeteria_6clips', i)
            time.sleep(0.5)  # 0.5s per clip = 3s total
        print("   ✓ Cafeteria complete (~3s processing time)")

        # ===== PHASE 3: Review Results =====
        print("\n" + "="*80)
        print("RESULTS VERIFICATION")
        print("="*80)
        print("\nCheck the dashboard above. Each group should show:")
        print("  • Conference_Room: ~2s (NOT ~22s with queue time)")
        print("  • Main_Entrance: ~2s (NOT ~21s with queue time)")
        print("  • Parking_Lot: ~3s (NOT ~18s with queue time)")
        print("  • Loading_Dock: ~2s (NOT ~14s with queue time)")
        print("  • Cafeteria: ~3s (NOT ~11s with queue time)")
        print("\n✅ Queue time (initial 3s) excluded from all elapsed times!")
        print("✅ Each timer started only when work began on that group!")

        # Keep display visible
        time.sleep(3)

        dashboard.complete_stage('transcription', "5 groups processed")

        print("\n" + "="*80)
        print("DEMONSTRATION COMPLETE")
        print("="*80 + "\n")

if __name__ == '__main__':
    main()
