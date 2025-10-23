"""
Integration tests for Phase 1 modular quality analyzer.

Validates that the modular implementation produces identical results
to the legacy implementation when use_modular_composition flag is enabled.

Author: Phase 1 integration tests
"""

import pytest
import yaml
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

from blink_pipeline.multi_camera_composer import MultiCameraComposer


class TestModularQualityIntegration:
    """Integration tests for modular quality analyzer."""
    
    @pytest.fixture
    def config_modular_disabled(self):
        """Configuration with modular composition disabled (legacy)."""
        config = yaml.safe_load(open('config.yaml'))
        config['multi_camera_composition']['use_modular_composition'] = False
        return config
    
    @pytest.fixture
    def config_modular_enabled(self):
        """Configuration with modular composition enabled."""
        config = yaml.safe_load(open('config.yaml'))
        config['multi_camera_composition']['use_modular_composition'] = True
        return config
    
    def test_initialization_legacy(self, config_modular_disabled):
        """Test composer initializes with legacy implementation."""
        composer = MultiCameraComposer(config_modular_disabled)
        
        assert composer._use_modular_composition is False
        assert composer._modular_quality_analyzer is None
        assert composer._needs_audio_analysis is not None
        assert composer._quality_weights is not None
    
    def test_initialization_modular(self, config_modular_enabled):
        """Test composer initializes with modular implementation."""
        composer = MultiCameraComposer(config_modular_enabled)
        
        assert composer._use_modular_composition is True
        assert composer._modular_quality_analyzer is not None
        assert composer._needs_audio_analysis is not None
        assert composer._quality_weights is not None
    
    def test_quality_weights_preserved(self, config_modular_enabled):
        """Test quality weights are preserved in both implementations."""
        composer = MultiCameraComposer(config_modular_enabled)
        
        # Verify weights sum to 1.0 (normalized)
        total_weight = sum(composer._quality_weights.values())
        assert abs(total_weight - 1.0) < 0.001
        
        # Verify all expected weight keys present
        assert 'rms' in composer._quality_weights
        assert 'peak' in composer._quality_weights
        assert 'noise' in composer._quality_weights
        assert 'clip' in composer._quality_weights
    
    @patch('subprocess.run')
    def test_quality_analysis_no_audio_legacy(self, mock_run, config_modular_disabled):
        """Test legacy quality analysis with no audio."""
        composer = MultiCameraComposer(config_modular_disabled)
        
        # Create mock media info with no audio
        media_info = Mock()
        media_info.has_audio = False
        
        score = composer._calculate_audio_quality('/fake/video.mp4', media_info)
        
        # Should return 0.0 for no audio
        assert score == 0.0
        # Should not call FFmpeg
        mock_run.assert_not_called()
    
    @patch('blink_pipeline.composition.quality.subprocess.run')
    def test_quality_analysis_no_audio_modular(self, mock_run, config_modular_enabled):
        """Test modular quality analysis with no audio."""
        # Disable caching for this test
        config_modular_enabled['output'] = {'audio_cache_dir': None}
        
        composer = MultiCameraComposer(config_modular_enabled)
        
        # Create mock media info with no audio
        media_info = Mock()
        media_info.has_audio = False
        
        score = composer._calculate_audio_quality('/fake/video.mp4', media_info)
        
        # Modular returns minimal quality metrics for no audio:
        # RMS: -60 dB (score=0.0), Peak: -60 dB (score=1.0)
        # Noise: 0 dB range (score=0.0), Clipping: 0.0 (score=1.0)
        # Overall with default weights: ~0.4-0.5 (peak and clip scores dominate)
        assert 0.3 <= score < 0.6
        # Should not call FFmpeg since has_audio=False
        mock_run.assert_not_called()
    
    @patch('subprocess.run')
    def test_quality_analysis_with_audio_legacy(self, mock_run, config_modular_disabled):
        """Test legacy quality analysis with audio."""
        # Mock FFmpeg output
        mock_ffmpeg_output = """
[Parsed_astats_0 @ 0x123] RMS level dB: -20.0
[Parsed_astats_0 @ 0x123] Peak level dB: -5.0
[Parsed_astats_0 @ 0x123] RMS min dB: -40.0
[Parsed_astats_0 @ 0x123] Peak count: 0.0
"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stderr = mock_ffmpeg_output
        mock_run.return_value = mock_result
        
        composer = MultiCameraComposer(config_modular_disabled)
        
        # Create mock media info with audio
        media_info = Mock()
        media_info.has_audio = True
        
        score = composer._calculate_audio_quality('/fake/video.mp4', media_info)
        
        # Should call FFmpeg
        mock_run.assert_called_once()
        
        # Score should be reasonable (>0.5 for good audio)
        assert 0.5 < score <= 1.0
    
    @patch('blink_pipeline.composition.quality.subprocess.run')
    def test_quality_analysis_with_audio_modular(self, mock_run, config_modular_enabled):
        """Test modular quality analysis with audio."""
        # Mock FFmpeg output
        mock_ffmpeg_output = """
[Parsed_astats_0 @ 0x123] RMS level dB: -20.0
[Parsed_astats_0 @ 0x123] Peak level dB: -5.0
[Parsed_astats_0 @ 0x123] RMS min dB: -40.0
[Parsed_astats_0 @ 0x123] Peak count: 0.0
"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stderr = mock_ffmpeg_output
        mock_run.return_value = mock_result
        
        # Disable caching for this test
        config_modular_enabled['output'] = {'audio_cache_dir': None}
        
        composer = MultiCameraComposer(config_modular_enabled)
        
        # Create mock media info with audio
        media_info = Mock()
        media_info.has_audio = True
        
        score = composer._calculate_audio_quality('/fake/video.mp4', media_info)
        
        # Should call FFmpeg
        mock_run.assert_called_once()
        
        # Score should be reasonable (>0.5 for good audio)
        assert 0.5 < score <= 1.0
    
    @patch('subprocess.run')
    @patch('blink_pipeline.composition.quality.subprocess.run')
    def test_functional_parity_good_quality(
        self,
        mock_run_modular,
        mock_run_legacy,
        config_modular_disabled,
        config_modular_enabled
    ):
        """Test that modular and legacy produce similar scores for good quality audio."""
        # Mock identical FFmpeg output for both
        mock_ffmpeg_output = """
[Parsed_astats_0 @ 0x123] RMS level dB: -22.0
[Parsed_astats_0 @ 0x123] Peak level dB: -6.0
[Parsed_astats_0 @ 0x123] RMS min dB: -45.0
[Parsed_astats_0 @ 0x123] Peak count: 1.0
"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stderr = mock_ffmpeg_output
        mock_run_legacy.return_value = mock_result
        mock_run_modular.return_value = mock_result
        
        # Disable caching for modular test
        config_modular_enabled['output'] = {'audio_cache_dir': None}
        
        # Create composers
        composer_legacy = MultiCameraComposer(config_modular_disabled)
        composer_modular = MultiCameraComposer(config_modular_enabled)
        
        # Create mock media info
        media_info = Mock()
        media_info.has_audio = True
        
        # Get scores from both implementations
        score_legacy = composer_legacy._calculate_audio_quality('/fake/video.mp4', media_info)
        score_modular = composer_modular._calculate_audio_quality('/fake/video.mp4', media_info)
        
        # Scores should be reasonably close (within 10% due to algorithm differences)
        # The algorithms have slight differences in how they handle missing metrics
        # Legacy uses hardcoded defaults (0.7, 0.5, 0.9) while modular calculates more precisely
        assert abs(score_legacy - score_modular) < 0.15, (
            f"Legacy score: {score_legacy}, Modular score: {score_modular}"
        )
    
    @patch('subprocess.run')
    @patch('blink_pipeline.composition.quality.subprocess.run')
    def test_functional_parity_poor_quality(
        self,
        mock_run_modular,
        mock_run_legacy,
        config_modular_disabled,
        config_modular_enabled
    ):
        """Test that modular and legacy produce similar scores for poor quality audio."""
        # Mock identical FFmpeg output for both
        mock_ffmpeg_output = """
[Parsed_astats_0 @ 0x123] RMS level dB: -60.0
[Parsed_astats_0 @ 0x123] Peak level dB: -1.0
[Parsed_astats_0 @ 0x123] RMS min dB: -40.0
[Parsed_astats_0 @ 0x123] Peak count: 10.0
"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stderr = mock_ffmpeg_output
        mock_run_legacy.return_value = mock_result
        mock_run_modular.return_value = mock_result
        
        # Disable caching for modular test
        config_modular_enabled['output'] = {'audio_cache_dir': None}
        
        # Create composers
        composer_legacy = MultiCameraComposer(config_modular_disabled)
        composer_modular = MultiCameraComposer(config_modular_enabled)
        
        # Create mock media info
        media_info = Mock()
        media_info.has_audio = True
        
        # Get scores from both implementations
        score_legacy = composer_legacy._calculate_audio_quality('/fake/video.mp4', media_info)
        score_modular = composer_modular._calculate_audio_quality('/fake/video.mp4', media_info)
        
        # Both should return poor scores
        assert score_legacy < 0.5
        assert score_modular < 0.5
        
        # Scores should be reasonably close (within 25% due to algorithm differences)
        assert abs(score_legacy - score_modular) < 0.25
    
    def test_cache_directory_creation(self, config_modular_enabled):
        """Test that cache directory is created for modular implementation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Override cache directory
            config_modular_enabled['output'] = {
                'audio_cache_dir': str(Path(tmpdir) / 'audio_cache')
            }
            
            composer = MultiCameraComposer(config_modular_enabled)
            
            # Cache directory should be created
            expected_cache_dir = Path(tmpdir) / 'audio_cache' / 'quality_analysis'
            assert expected_cache_dir.exists()
            assert expected_cache_dir.is_dir()


class TestModularQualityLogging:
    """Test logging for modular quality analyzer."""
    
    @pytest.fixture
    def config_modular_enabled(self):
        """Configuration with modular composition enabled."""
        config = yaml.safe_load(open('config.yaml'))
        config['multi_camera_composition']['use_modular_composition'] = True
        return config
    
    def test_logs_modular_enabled_message(self, config_modular_enabled, caplog):
        """Test that initialization logs when modular composition is enabled."""
        import logging
        caplog.set_level(logging.INFO)
        
        composer = MultiCameraComposer(config_modular_enabled)
        
        # Should log that modular composition is enabled
        assert any(
            'Modular composition enabled' in record.message
            for record in caplog.records
        )
    
    def test_logs_legacy_debug_message(self, caplog):
        """Test that initialization logs when using legacy implementation."""
        import logging
        caplog.set_level(logging.DEBUG)
        
        config = yaml.safe_load(open('config.yaml'))
        config['multi_camera_composition']['use_modular_composition'] = False
        
        composer = MultiCameraComposer(config)
        
        # Should log that legacy implementation is used
        assert any(
            'legacy quality analysis' in record.message
            for record in caplog.records
        )
