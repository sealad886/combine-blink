# Blink Filename Format Guide

## Overview

This document describes the expected filename and directory structure for Blink video files.

## Filename Format

```
HH-MM-SS_CameraNameG<suffix>.mp4
```

### Components

| Component | Description | Example |
|-----------|-------------|---------|
| `HH-MM-SS` | Hour-Minute-Second timestamp (24-hour format) | `08-37-43` |
| `CameraName` | Camera identifier (alphanumeric, ends before 'G') | `Corner`, `FrontDoor`, `Backyard` |
| `G<suffix>` | Unique identifier starting with 'G' | `G8T1K0013255014P_081` |

### Examples

```
08-37-43_CornerG8T1K0013255014P_081.mp4
14-22-15_FrontDoorG1234567890ABC_001.mp4
23-59-59_BackyardG9876543210XYZ_999.mp4
00-00-01_GarageG1A2B3C4D5E_042.mp4
```

## Directory Structure

Videos must be organized in date-named folders:

```
input_videos/
  ├── 2025-10-19/
  │   ├── 08-37-43_CornerG8T1K0013255014P_081.mp4
  │   ├── 08-38-15_FrontDoorG9876543210XYZ_082.mp4
  │   └── 14-22-30_BackyardG1234567890ABC_083.mp4
  └── 2025-10-20/
      └── 09-15-00_CornerG5678901234DEF_001.mp4
```

## Supported Date Formats

The parent directory name is parsed to extract the date. Supported formats:

| Format | Example | Description |
|--------|---------|-------------|
| `%Y-%m-%d` | `2025-10-19` | ISO 8601 (recommended) |
| `%Y%m%d` | `20251019` | Compact format |
| `%Y_%m_%d` | `2025_10_19` | Underscore-separated |
| `%m-%d-%Y` | `10-19-2025` | US format (MM-DD-YYYY) |
| `%d-%m-%Y` | `19-10-2025` | European format (DD-MM-YYYY) |

## Complete Example

For a video recorded on **October 19, 2025** at **8:37:43 AM** by the **Corner** camera:

- **Filename**: `08-37-43_CornerG8T1K0013255014P_081.mp4`
- **Directory**: `2025-10-19/`
- **Full Path**: `input_videos/2025-10-19/08-37-43_CornerG8T1K0013255014P_081.mp4`

**Parsed Result**:
- Camera: `Corner`
- DateTime: `2025-10-19 08:37:43`

## Configuration

The regex pattern in `config.yaml`:

```yaml
discovery:
  filename_pattern: '(\d{2}-\d{2}-\d{2})_([a-zA-Z0-9]+)G.+\.mp4'
  date_folder_patterns:
    - '%Y-%m-%d'
    - '%Y%m%d'
    - '%Y_%m_%d'
    - '%m-%d-%Y'
    - '%d-%m-%Y'
```

## Testing

Run the included test script to verify filename parsing:

```bash
python3 test_filename_parsing.py
```

This will validate:
- Regex pattern matching
- Camera name extraction
- Date folder parsing
- Complete datetime assembly
