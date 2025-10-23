import os
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
import logging

def parse_date_from_directory(dir_path: str, date_patterns: Optional[List[str]] = None) -> Optional[datetime]:
    """
    Attempts to parse a date from a directory name using common date formats.

    Args:
        dir_path: The directory path to parse
        date_patterns: List of strptime format strings to try

    Returns:
        datetime object if successful, None otherwise
    """
    if date_patterns is None:
        date_patterns = [
            '%Y-%m-%d',   # 2025-10-19
            '%Y%m%d',     # 20251019
            '%Y_%m_%d',   # 2025_10_19
            '%m-%d-%Y',   # 10-19-2025
            '%d-%m-%Y',   # 19-10-2025
        ]

    dir_name = os.path.basename(dir_path)

    for pattern in date_patterns:
        try:
            return datetime.strptime(dir_name, pattern)
        except ValueError:
            continue

    return None


def discover_files(input_dir: str, pattern: str, config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Recursively finds all video files in the input directory that match the
    Blink filename pattern.

    Args:
        input_dir (str): The directory to search for videos.
        pattern (str): The regex pattern to match and parse filenames.
        config (dict, optional): Configuration dict containing date_folder_patterns

    Returns:
        list: A sorted list of dictionaries, where each dictionary contains
              information about a video file (path, camera, datetime).
    """
    date_patterns = None
    if config and 'discovery' in config and 'date_folder_patterns' in config['discovery']:
        date_patterns = config['discovery']['date_folder_patterns']

    video_files = []
    filename_re = re.compile(pattern)

    for root, _, files in os.walk(input_dir):
        for file in files:
            if file.endswith('.mp4'):
                match = filename_re.match(file)
                if match:
                    try:
                        timestamp_str, camera_name = match.groups()

                        # Parse time from filename (HH-MM-SS format)
                        time_obj = datetime.strptime(timestamp_str, '%H-%M-%S')

                        # Try to parse date from parent directory
                        date_obj = parse_date_from_directory(root, date_patterns)

                        if date_obj:
                            # Combine date from directory with time from filename
                            dt_obj = date_obj.replace(
                                hour=time_obj.hour,
                                minute=time_obj.minute,
                                second=time_obj.second
                            )
                        else:
                            # Fallback: use today's date if directory name doesn't contain a date
                            logging.warning(
                                f"Could not parse date from directory '{os.path.basename(root)}'. "
                                f"Using today's date as fallback."
                            )
                            dt_obj = time_obj.replace(
                                year=datetime.now().year,
                                month=datetime.now().month,
                                day=datetime.now().day
                            )

                        video_files.append({
                            'full_path': os.path.join(root, file),
                            'filename': file,
                            'camera': camera_name,
                            'datetime': dt_obj,
                            'directory': os.path.basename(root)
                        })
                    except (ValueError, IndexError) as e:
                        logging.warning(f"Could not parse filename '{file}': {e}")
                else:
                    logging.warning(f"Filename '{file}' did not match expected pattern.")

    # Sort files chronologically to make grouping easier
    video_files.sort(key=lambda x: x['datetime'])
    return video_files
