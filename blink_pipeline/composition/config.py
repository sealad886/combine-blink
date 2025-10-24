"""
Configuration Models Module

Type-safe configuration parsing using Pydantic models.
Replaces manual dictionary parsing with validated, typed configuration.

Classes:
- AudioQualityWeights: Weights for audio quality metrics
- AlignmentConfig: Audio alignment configuration
- PeopleDetectionConfig: People detection configuration
- TimestampOverlayConfig: Timestamp overlay configuration
- EncodingConfig: Video encoding configuration
- CompositionConfig: Main composition configuration

Author: Phase 1 implementation
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class AudioQualityWeights(BaseModel):
    """Weights for audio quality scoring metrics."""

    rms: float = Field(default=0.4, ge=0.0, le=1.0, description="RMS level weight")
    peak: float = Field(default=0.2, ge=0.0, le=1.0, description="Peak level weight")
    noise: float = Field(default=0.2, ge=0.0, le=1.0, description="Noise floor weight")
    clipping: float = Field(default=0.3, ge=0.0, le=1.0, description="Clipping rate weight")

    @field_validator('rms', 'peak', 'noise', 'clipping')
    @classmethod
    def validate_positive(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Weight must be non-negative")
        return v


class AlignmentConfig(BaseModel):
    """Configuration for audio alignment."""

    enabled: bool = Field(default=True, description="Enable audio alignment")
    max_shift_seconds: float = Field(default=1.5, ge=0.0, description="Maximum alignment shift")
    analysis_window_seconds: float = Field(default=12.0, gt=0.0, description="Analysis window duration")
    hop_seconds: float = Field(default=6.0, gt=0.0, description="Hop between windows")
    sample_rate: int = Field(default=48000, gt=0, description="Downsample rate for alignment")
    bandpass: bool = Field(default=True, description="Apply bandpass filter")
    highpass_hz: float = Field(default=80.0, ge=0.0, description="Highpass filter cutoff")
    lowpass_hz: float = Field(default=8000.0, gt=0.0, description="Lowpass filter cutoff")
    estimate_drift: bool = Field(default=True, description="Estimate and correct drift")


class PeopleDetectionConfig(BaseModel):
    """Configuration for people detection."""

    enabled: bool = Field(default=True, description="Enable people detection")
    backend: str = Field(default='auto', description="Detection backend (auto, vision, huggingface)")
    sample_frames: int = Field(default=12, gt=0, description="Number of frames to sample")
    resize_width: int = Field(default=480, gt=0, description="Resize width for detection")
    min_frame_width: int = Field(default=320, gt=0, description="Minimum frame width")
    model_name: Optional[str] = Field(default='hustvl/yolos-tiny', description="HuggingFace model name")
    revision: Optional[str] = Field(default=None, description="Model revision")
    score_threshold: float = Field(default=0.65, ge=0.0, le=1.0, description="Detection confidence threshold")
    min_count: int = Field(default=1, ge=0, description="Minimum people count for selection")


class TimestampOverlayConfig(BaseModel):
    """Configuration for timestamp overlay."""

    enabled: bool = Field(default=True, description="Enable timestamp overlay")
    font: str = Field(default='Arial', description="Font name")
    font_size: int = Field(default=24, gt=0, description="Font size")
    margin_v: int = Field(default=20, ge=0, description="Vertical margin")
    margin_r: int = Field(default=20, ge=0, description="Right margin")
    dst_offset_hours: int = Field(default=1, description="DST offset in hours")


class EncodingConfig(BaseModel):
    """Configuration for video encoding."""

    use_hw_encode: bool = Field(default=True, description="Use hardware encoding")
    hw_codec: str = Field(default='h264_videotoolbox', description="Hardware codec")
    x264_preset: Optional[str] = Field(default=None, description="Software encoding preset")
    x264_crf: Optional[int] = Field(default=None, ge=0, le=51, description="Software encoding CRF")
    bitrate: str = Field(default='8000k', description="Target bitrate")


class AudioCleanupConfig(BaseModel):
    """Configuration for audio cleanup."""

    enabled: bool = Field(default=True, description="Enable audio cleanup")
    highpass_hz: float = Field(default=80.0, ge=0.0, description="Highpass filter cutoff")
    lowpass_hz: float = Field(default=8000.0, gt=0.0, description="Lowpass filter cutoff")
    denoise: bool = Field(default=True, description="Apply denoising")
    denoise_nf: float = Field(default=-25.0, description="Noise floor reference (dB)")
    loudness_normalize: bool = Field(default=True, description="Apply loudness normalization")
    loudnorm_target_i: float = Field(default=-23.0, description="Target integrated loudness (LUFS)")
    loudnorm_target_tp: float = Field(default=-2.0, description="Target true peak (dBTP)")
    loudnorm_target_lra: float = Field(default=11.0, description="Target loudness range (LU)")
    extra_filters: List[str] = Field(default_factory=list, description="Additional FFmpeg filters")


class AudioMixConfig(BaseModel):
    """Configuration for audio mixing and transitions (crossfades, ducking)."""

    # Crossfade parameters between consecutive audio segments
    crossfade_seconds: float = Field(default=0.06, ge=0.0, description="Crossfade duration in seconds")
    curve1: str = Field(default='tri', description="Acrossfade curve for outgoing segment (afade curve names)")
    curve2: str = Field(default='tri', description="Acrossfade curve for incoming segment (afade curve names)")
    overlap: bool = Field(default=True, description="Whether to overlap segment ends during crossfade")

    # Optional ducking (reserved for future use)
    ducking_enabled: bool = Field(default=False, description="Enable sidechain ducking (not yet implemented)")
    ducking_threshold: float = Field(default=0.125, ge=0.0, description="Sidechain threshold for ducking")
    ducking_ratio: float = Field(default=2.0, ge=1.0, description="Compression ratio for ducking")
    ducking_attack_ms: float = Field(default=20.0, ge=0.01, description="Attack time in ms for ducking")
    ducking_release_ms: float = Field(default=250.0, ge=0.01, description="Release time in ms for ducking")
    ducking_makeup: float = Field(default=1.0, ge=1.0, description="Makeup gain for ducked signal")


class CompositionConfig(BaseModel):
    """Main configuration for multi-camera composition."""

    enable_composition: bool = Field(default=True, description="Enable multi-camera composition")
    use_modular_composition: bool = Field(default=False, description="Use modular architecture")
    switching_strategy: str = Field(default='speech_people', description="Camera switching strategy")
    switching_interval: float = Field(default=5.0, gt=0.0, description="Switching interval (seconds)")
    transition_style: str = Field(default='cut', description="Transition style (cut, crossfade)")
    transition_duration: float = Field(default=0.28, ge=0.0, description="Transition duration (seconds)")
    audio_crossfade_seconds: float = Field(default=0.06, ge=0.0, description="Audio crossfade duration (deprecated; use audio_mix.crossfade_seconds)")
    audio_source: str = Field(default='best_quality', description="Audio source selection strategy")
    single_pass_filter_complex: bool = Field(default=False, description="Use single-pass rendering")

    # Nested configurations
    audio_quality_weights: AudioQualityWeights = Field(default_factory=AudioQualityWeights)
    audio_alignment: AlignmentConfig = Field(default_factory=AlignmentConfig)
    people_detection: PeopleDetectionConfig = Field(default_factory=PeopleDetectionConfig)
    timestamp_overlay: TimestampOverlayConfig = Field(default_factory=TimestampOverlayConfig)
    encoding: EncodingConfig = Field(default_factory=EncodingConfig)
    audio_cleanup: AudioCleanupConfig = Field(default_factory=AudioCleanupConfig)
    audio_mix: AudioMixConfig = Field(default_factory=AudioMixConfig)

    @field_validator('switching_strategy')
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        valid = ['time_based', 'round_robin', 'audio_quality', 'speech_people']
        if v not in valid:
            raise ValueError(f"Invalid switching_strategy: {v}. Must be one of {valid}")
        return v

    @field_validator('transition_style')
    @classmethod
    def validate_transition(cls, v: str) -> str:
        valid = ['cut', 'crossfade']
        if v not in valid:
            raise ValueError(f"Invalid transition_style: {v}. Must be one of {valid}")
        return v

    @field_validator('audio_source')
    @classmethod
    def validate_audio_source(cls, v: str) -> str:
        valid = ['best_quality', 'first', 'longest']
        if v not in valid:
            raise ValueError(f"Invalid audio_source: {v}. Must be one of {valid}")
        return v

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'CompositionConfig':
        """Create CompositionConfig from dictionary (e.g., from YAML)."""
        # Backward-compat shim: if top-level audio_crossfade_seconds provided and
        # audio_mix.crossfade_seconds not provided, propagate value.
        cfg = dict(config_dict)
        mix = dict(cfg.get('audio_mix') or {})
        if 'audio_crossfade_seconds' in cfg and 'crossfade_seconds' not in mix:
            try:
                v = float(cfg.get('audio_crossfade_seconds'))
                if v >= 0.0:
                    mix['crossfade_seconds'] = v
            except (TypeError, ValueError):
                pass
        if mix:
            cfg['audio_mix'] = mix
        return cls(**cfg)


# Placeholder for future expansion
__all__ = [
    'AudioQualityWeights',
    'AlignmentConfig',
    'PeopleDetectionConfig',
    'TimestampOverlayConfig',
    'EncodingConfig',
    'AudioCleanupConfig',
    'AudioMixConfig',
    'CompositionConfig',
]
