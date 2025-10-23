"""
Unit Tests for Configuration Models

Tests the Pydantic configuration models in blink_pipeline/composition/config.py.

Coverage targets:
- Model instantiation and defaults
- Field validation (ranges, enums)
- Nested model composition
- from_dict factory method
- Edge cases and invalid inputs

Author: Phase 1 testing
"""

import pytest
from pydantic import ValidationError
from blink_pipeline.composition.config import (
    AudioQualityWeights,
    AlignmentConfig,
    PeopleDetectionConfig,
    TimestampOverlayConfig,
    EncodingConfig,
    AudioCleanupConfig,
    CompositionConfig,
)


class TestAudioQualityWeights:
    """Test AudioQualityWeights model."""
    
    def test_default_values(self):
        """Test default weight values."""
        weights = AudioQualityWeights()
        assert weights.rms == 0.4
        assert weights.peak == 0.2
        assert weights.noise == 0.2
        assert weights.clipping == 0.3
    
    def test_valid_weights(self):
        """Test valid weight assignment."""
        weights = AudioQualityWeights(rms=0.5, peak=0.25, noise=0.15, clipping=0.1)
        assert weights.rms == 0.5
        assert weights.peak == 0.25
        assert weights.noise == 0.15
        assert weights.clipping == 0.1
    
    def test_negative_weight_fails(self):
        """Test that negative weights are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            AudioQualityWeights(rms=-0.1)
        assert 'rms' in str(exc_info.value)
    
    def test_weight_above_one(self):
        """Test that weights > 1.0 are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            AudioQualityWeights(rms=1.5)
        assert 'rms' in str(exc_info.value)
    
    def test_boundary_values(self):
        """Test boundary values 0.0 and 1.0."""
        weights = AudioQualityWeights(rms=0.0, peak=1.0, noise=0.0, clipping=1.0)
        assert weights.rms == 0.0
        assert weights.peak == 1.0


class TestAlignmentConfig:
    """Test AlignmentConfig model."""
    
    def test_default_values(self):
        """Test default alignment configuration."""
        config = AlignmentConfig()
        assert config.enabled is True
        assert config.max_shift_seconds == 1.5
        assert config.analysis_window_seconds == 12.0
        assert config.hop_seconds == 6.0
        assert config.sample_rate == 48000
        assert config.bandpass is True
        assert config.highpass_hz == 80.0
        assert config.lowpass_hz == 8000.0
        assert config.estimate_drift is True
    
    def test_custom_values(self):
        """Test custom configuration."""
        config = AlignmentConfig(
            enabled=False,
            max_shift_seconds=2.0,
            sample_rate=44100
        )
        assert config.enabled is False
        assert config.max_shift_seconds == 2.0
        assert config.sample_rate == 44100
    
    def test_negative_max_shift_fails(self):
        """Test that negative max_shift is rejected."""
        with pytest.raises(ValidationError):
            AlignmentConfig(max_shift_seconds=-1.0)
    
    def test_zero_window_fails(self):
        """Test that zero window duration is rejected."""
        with pytest.raises(ValidationError):
            AlignmentConfig(analysis_window_seconds=0.0)
    
    def test_negative_sample_rate_fails(self):
        """Test that negative sample rate is rejected."""
        with pytest.raises(ValidationError):
            AlignmentConfig(sample_rate=-1000)


class TestPeopleDetectionConfig:
    """Test PeopleDetectionConfig model."""
    
    def test_default_values(self):
        """Test default people detection configuration."""
        config = PeopleDetectionConfig()
        assert config.enabled is True
        assert config.backend == 'auto'
        assert config.sample_frames == 12
        assert config.resize_width == 480
        assert config.min_frame_width == 320
        assert config.model_name == 'hustvl/yolos-tiny'
        assert config.revision is None
        assert config.score_threshold == 0.65
        assert config.min_count == 1
    
    def test_custom_backend(self):
        """Test custom backend selection."""
        config = PeopleDetectionConfig(backend='vision')
        assert config.backend == 'vision'
    
    def test_zero_sample_frames_fails(self):
        """Test that zero sample_frames is rejected."""
        with pytest.raises(ValidationError):
            PeopleDetectionConfig(sample_frames=0)
    
    def test_threshold_out_of_range_fails(self):
        """Test that invalid thresholds are rejected."""
        with pytest.raises(ValidationError):
            PeopleDetectionConfig(score_threshold=1.5)
        
        with pytest.raises(ValidationError):
            PeopleDetectionConfig(score_threshold=-0.1)
    
    def test_negative_min_count_fails(self):
        """Test that negative min_count is rejected."""
        with pytest.raises(ValidationError):
            PeopleDetectionConfig(min_count=-1)


class TestTimestampOverlayConfig:
    """Test TimestampOverlayConfig model."""
    
    def test_default_values(self):
        """Test default timestamp configuration."""
        config = TimestampOverlayConfig()
        assert config.enabled is True
        assert config.font == 'Arial'
        assert config.font_size == 24
        assert config.margin_v == 20
        assert config.margin_r == 20
        assert config.dst_offset_hours == 1
    
    def test_custom_values(self):
        """Test custom timestamp configuration."""
        config = TimestampOverlayConfig(
            font='Helvetica',
            font_size=32,
            dst_offset_hours=0
        )
        assert config.font == 'Helvetica'
        assert config.font_size == 32
        assert config.dst_offset_hours == 0
    
    def test_zero_font_size_fails(self):
        """Test that zero font size is rejected."""
        with pytest.raises(ValidationError):
            TimestampOverlayConfig(font_size=0)
    
    def test_negative_margins_fail(self):
        """Test that negative margins are rejected."""
        with pytest.raises(ValidationError):
            TimestampOverlayConfig(margin_v=-10)


class TestEncodingConfig:
    """Test EncodingConfig model."""
    
    def test_default_values(self):
        """Test default encoding configuration."""
        config = EncodingConfig()
        assert config.use_hw_encode is True
        assert config.hw_codec == 'h264_videotoolbox'
        assert config.x264_preset is None
        assert config.x264_crf is None
        assert config.bitrate == '8000k'
    
    def test_software_encoding(self):
        """Test software encoding configuration."""
        config = EncodingConfig(
            use_hw_encode=False,
            x264_preset='faster',
            x264_crf=20
        )
        assert config.use_hw_encode is False
        assert config.x264_preset == 'faster'
        assert config.x264_crf == 20
    
    def test_invalid_crf_fails(self):
        """Test that invalid CRF values are rejected."""
        with pytest.raises(ValidationError):
            EncodingConfig(x264_crf=-1)
        
        with pytest.raises(ValidationError):
            EncodingConfig(x264_crf=52)


class TestAudioCleanupConfig:
    """Test AudioCleanupConfig model."""
    
    def test_default_values(self):
        """Test default audio cleanup configuration."""
        config = AudioCleanupConfig()
        assert config.enabled is True
        assert config.highpass_hz == 80.0
        assert config.lowpass_hz == 8000.0
        assert config.denoise is True
        assert config.denoise_nf == -25.0
        assert config.loudness_normalize is True
        assert config.loudnorm_target_i == -23.0
        assert config.loudnorm_target_tp == -2.0
        assert config.loudnorm_target_lra == 11.0
        assert config.extra_filters == []
    
    def test_custom_filters(self):
        """Test custom filter configuration."""
        config = AudioCleanupConfig(
            extra_filters=['highpass=f=100', 'volume=1.5']
        )
        assert len(config.extra_filters) == 2
        assert 'highpass=f=100' in config.extra_filters
    
    def test_negative_highpass_fails(self):
        """Test that negative highpass is rejected."""
        with pytest.raises(ValidationError):
            AudioCleanupConfig(highpass_hz=-50.0)
    
    def test_zero_lowpass_fails(self):
        """Test that zero lowpass is rejected."""
        with pytest.raises(ValidationError):
            AudioCleanupConfig(lowpass_hz=0.0)


class TestCompositionConfig:
    """Test CompositionConfig model (main configuration)."""
    
    def test_default_values(self):
        """Test default composition configuration."""
        config = CompositionConfig()
        assert config.enable_composition is True
        assert config.use_modular_composition is False
        assert config.switching_strategy == 'speech_people'
        assert config.switching_interval == 5.0
        assert config.transition_style == 'cut'
        assert config.transition_duration == 0.28
        assert config.audio_crossfade_seconds == 0.06
        assert config.audio_source == 'best_quality'
        assert config.single_pass_filter_complex is False
        
        # Nested configs should be initialized
        assert isinstance(config.audio_quality_weights, AudioQualityWeights)
        assert isinstance(config.audio_alignment, AlignmentConfig)
        assert isinstance(config.people_detection, PeopleDetectionConfig)
        assert isinstance(config.timestamp_overlay, TimestampOverlayConfig)
        assert isinstance(config.encoding, EncodingConfig)
        assert isinstance(config.audio_cleanup, AudioCleanupConfig)
    
    def test_custom_strategy(self):
        """Test custom switching strategy."""
        config = CompositionConfig(switching_strategy='time_based')
        assert config.switching_strategy == 'time_based'
    
    def test_invalid_strategy_fails(self):
        """Test that invalid strategy is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            CompositionConfig(switching_strategy='invalid_strategy')
        assert 'switching_strategy' in str(exc_info.value)
    
    def test_valid_strategies(self):
        """Test all valid switching strategies."""
        valid_strategies = ['time_based', 'round_robin', 'audio_quality', 'speech_people']
        for strategy in valid_strategies:
            config = CompositionConfig(switching_strategy=strategy)
            assert config.switching_strategy == strategy
    
    def test_invalid_transition_fails(self):
        """Test that invalid transition style is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            CompositionConfig(transition_style='invalid_transition')
        assert 'transition_style' in str(exc_info.value)
    
    def test_valid_transitions(self):
        """Test all valid transition styles."""
        valid_transitions = ['cut', 'crossfade']
        for transition in valid_transitions:
            config = CompositionConfig(transition_style=transition)
            assert config.transition_style == transition
    
    def test_invalid_audio_source_fails(self):
        """Test that invalid audio source is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            CompositionConfig(audio_source='invalid_source')
        assert 'audio_source' in str(exc_info.value)
    
    def test_valid_audio_sources(self):
        """Test all valid audio sources."""
        valid_sources = ['best_quality', 'first', 'longest']
        for source in valid_sources:
            config = CompositionConfig(audio_source=source)
            assert config.audio_source == source
    
    def test_nested_config_override(self):
        """Test overriding nested configuration."""
        config = CompositionConfig(
            audio_quality_weights=AudioQualityWeights(rms=0.5, peak=0.3, noise=0.1, clipping=0.1),
            audio_alignment=AlignmentConfig(enabled=False)
        )
        assert config.audio_quality_weights.rms == 0.5
        assert config.audio_alignment.enabled is False
    
    def test_from_dict_factory(self):
        """Test from_dict factory method."""
        config_dict = {
            'enable_composition': True,
            'use_modular_composition': True,
            'switching_strategy': 'audio_quality',
            'audio_quality_weights': {
                'rms': 0.5,
                'peak': 0.25,
                'noise': 0.15,
                'clipping': 0.1
            }
        }
        config = CompositionConfig.from_dict(config_dict)
        assert config.enable_composition is True
        assert config.use_modular_composition is True
        assert config.switching_strategy == 'audio_quality'
        assert config.audio_quality_weights.rms == 0.5
    
    def test_from_dict_with_yaml_structure(self):
        """Test from_dict with typical YAML structure."""
        # Simulate config loaded from YAML
        yaml_config = {
            'switching_strategy': 'speech_people',
            'transition_style': 'cut',
            'audio_source': 'best_quality',
            'audio_alignment': {
                'enabled': True,
                'max_shift_seconds': 2.0
            },
            'encoding': {
                'use_hw_encode': True,
                'bitrate': '10000k'
            }
        }
        config = CompositionConfig.from_dict(yaml_config)
        assert config.switching_strategy == 'speech_people'
        assert config.audio_alignment.max_shift_seconds == 2.0
        assert config.encoding.bitrate == '10000k'
    
    def test_zero_interval_fails(self):
        """Test that zero switching interval is rejected."""
        with pytest.raises(ValidationError):
            CompositionConfig(switching_interval=0.0)
    
    def test_negative_crossfade_fails(self):
        """Test that negative crossfade is rejected."""
        with pytest.raises(ValidationError):
            CompositionConfig(audio_crossfade_seconds=-0.1)


class TestConfigIntegration:
    """Integration tests for configuration models."""
    
    def test_complete_config_from_dict(self):
        """Test loading complete configuration from dict."""
        complete_config = {
            'enable_composition': True,
            'use_modular_composition': False,
            'switching_strategy': 'speech_people',
            'switching_interval': 5.0,
            'transition_style': 'cut',
            'audio_quality_weights': {
                'rms': 0.4,
                'peak': 0.2,
                'noise': 0.2,
                'clipping': 0.3
            },
            'audio_alignment': {
                'enabled': True,
                'max_shift_seconds': 1.5
            },
            'people_detection': {
                'enabled': True,
                'backend': 'vision'
            },
            'encoding': {
                'use_hw_encode': True,
                'hw_codec': 'h264_videotoolbox',
                'bitrate': '8000k'
            }
        }
        config = CompositionConfig.from_dict(complete_config)
        assert config.enable_composition is True
        assert config.switching_strategy == 'speech_people'
        assert config.audio_alignment.max_shift_seconds == 1.5
        assert config.people_detection.backend == 'vision'
        assert config.encoding.bitrate == '8000k'
    
    def test_partial_config_uses_defaults(self):
        """Test that partial configuration uses defaults for missing fields."""
        partial_config = {
            'switching_strategy': 'time_based'
        }
        config = CompositionConfig.from_dict(partial_config)
        assert config.switching_strategy == 'time_based'
        # Defaults should be used
        assert config.switching_interval == 5.0
        assert config.transition_style == 'cut'
        assert config.audio_quality_weights.rms == 0.4


class TestConfigValidation:
    """Test edge cases and validation."""
    
    def test_empty_dict(self):
        """Test creating config from empty dict."""
        config = CompositionConfig.from_dict({})
        # Should use all defaults
        assert config.switching_strategy == 'speech_people'
        assert config.audio_source == 'best_quality'
    
    def test_invalid_nested_config_fails(self):
        """Test that invalid nested config is rejected."""
        with pytest.raises(ValidationError):
            CompositionConfig(
                audio_quality_weights=AudioQualityWeights(rms=-0.1)  # Invalid
            )
    
    def test_extra_fields_ignored(self):
        """Test that extra unknown fields are handled."""
        config_dict = {
            'switching_strategy': 'time_based',
            'unknown_field': 'should_be_ignored'
        }
        # Pydantic should either ignore or raise depending on config
        # Default behavior is to ignore extra fields
        config = CompositionConfig.from_dict(config_dict)
        assert config.switching_strategy == 'time_based'


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--cov=blink_pipeline.composition.config', '--cov-report=term-missing'])
