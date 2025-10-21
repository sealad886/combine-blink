#!/usr/bin/env python3
"""
Test script to validate the filename regex pattern and date parsing.
"""
import re
from datetime import datetime

# Test the regex pattern
pattern = r'(\d{2}-\d{2}-\d{2})_([a-zA-Z0-9]+)G.+\.mp4'
test_filenames = [
    "08-37-43_CornerG8T1K0013255014P_081.mp4",
    "14-22-15_FrontDoorG1234567890ABC_001.mp4",
    "23-59-59_BackyardG9876543210XYZ_999.mp4",
    "00-00-01_GarageG1A2B3C4D5E_042.mp4",
]

print("=" * 70)
print("Testing Filename Regex Pattern")
print("=" * 70)
print(f"Pattern: {pattern}\n")

filename_re = re.compile(pattern)

for filename in test_filenames:
    match = filename_re.match(filename)
    if match:
        timestamp, camera = match.groups()
        print(f"✓ MATCH: {filename}")
        print(f"  └─ Time: {timestamp}, Camera: {camera}")
    else:
        print(f"✗ NO MATCH: {filename}")
    print()

# Test date parsing from directory names
print("=" * 70)
print("Testing Date Folder Parsing")
print("=" * 70)

date_patterns = [
    '%Y-%m-%d',   # 2025-10-19
    '%Y%m%d',     # 20251019
    '%Y_%m_%d',   # 2025_10_19
    '%m-%d-%Y',   # 10-19-2025
    '%d-%m-%Y',   # 19-10-2025
]

test_folders = [
    "2025-10-19",
    "20251019",
    "2025_10_19",
    "10-19-2025",
    "19-10-2025",
]

for folder in test_folders:
    parsed = None
    for pattern in date_patterns:
        try:
            parsed = datetime.strptime(folder, pattern)
            print(f"✓ PARSED: {folder:15s} → {parsed.strftime('%Y-%m-%d')} (pattern: {pattern})")
            break
        except ValueError:
            continue
    if not parsed:
        print(f"✗ FAILED: {folder}")

print("\n" + "=" * 70)
print("Complete Example")
print("=" * 70)
print("\nFile: 08-37-43_CornerG8T1K0013255014P_081.mp4")
print("Directory: 2025-10-19")
print("\nParsed result:")
print("  Camera: Corner")
print("  DateTime: 2025-10-19 08:37:43")
print("=" * 70)
