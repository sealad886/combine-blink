"""
Pipeline Stage Keys

Centralized constants for all pipeline stages.
Using an enum provides type safety, IDE autocomplete, and prevents typos.

Usage:
    from blink_pipeline.stages import StageKey

    dashboard.start_stage(StageKey.VALIDATION, total_videos)
    dashboard.complete_stage(StageKey.TRANSCRIPTION)
"""

from enum import Enum


class StageKey(str, Enum):
    """
    Enum for all pipeline stage keys.

    Inherits from str to maintain backward compatibility with string-based APIs
    while providing type safety and IDE autocomplete.

    Each stage represents a major phase in the video processing pipeline:
    - VALIDATION: Video validation and repair
    - TRANSCRIPTION: Audio transcription and speaker diarization
    - SPEAKER_ID: Speaker identification and voice sample creation
    - GROUPING: Organizing videos into logical groups
    - MERGE: Merging videos within each group
    - FINAL_TRANSCRIPTION: Final transcription of merged videos
    - COMPOSITION: Multi-camera composition (future)
    """

    VALIDATION = "validation"
    TRANSCRIPTION = "transcription"
    SPEAKER_ID = "speaker_id"
    GROUPING = "grouping"
    MERGE = "merge"
    FINAL_TRANSCRIPTION = "final_transcription"
    COMPOSITION = "composition"
    SPEAKER_PROFILES = "speaker_profiles"

    def __str__(self) -> str:
        """Return the string value for seamless string compatibility."""
        return self.value


# List of all valid stage keys for validation
ALL_STAGE_KEYS = {key.value for key in StageKey}


def validate_stage_key(stage_key: str) -> None:
    """
    Validate that a stage key is recognized.

    Args:
        stage_key: The stage key to validate

    Raises:
        ValueError: If the stage key is not valid
    """
    if stage_key not in ALL_STAGE_KEYS:
        valid_keys = ", ".join(sorted(ALL_STAGE_KEYS))
        raise ValueError(
            f"Invalid stage key: '{stage_key}'. "
            f"Valid keys are: {valid_keys}"
        )
