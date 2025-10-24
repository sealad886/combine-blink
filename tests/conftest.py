"""
Pytest configuration and shared fixtures for combine-blink tests.

This module provides reusable fixtures and configuration for all test modules.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any
from unittest.mock import MagicMock, Mock
import pytest

# Ensure src is in path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================================
# Session-level Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def test_data_dir(project_root) -> Path:
    """Return the test data directory."""
    return project_root / "tests" / "data"


# ============================================================================
# Configuration Fixtures
# ============================================================================

@pytest.fixture
def base_config() -> Dict[str, Any]:
    """
    Provide a minimal valid configuration for testing.

    This can be customized by tests as needed.
    """
    return {
        'paths': {
            'input_dir': '25-10-15',
            'output_dir': 'output',
            'videos_dir': 'merged_videos',
            'transcripts_dir': 'transcripts',
            'speakers_dir': 'speaker_voice_samples'
        },
        'discovery': {
            'filename_pattern': r'(\d{2}-\d{2}-\d{2})_([a-zA-Z0-9]+)G.+\.mp4',
            'date_folder_patterns': ['%Y-%m-%d', '%Y%m%d']
        },
        'grouping': {
            'max_time_diff_seconds': 300
        },
        'multi_camera_composition': {
            'enable_composition': True,
            'switching_strategy': 'speech_people',
            'people_detection': {
                'enabled': True,
                'backend': 'auto',
                'sample_frames': 3
            }
        },
        'transcription': {
            'always_repair': False,
            'repair_cache_dir': 'output/repaired_cache',
            'repair_strategy': 'fill',
            'whisper': {
                'prefer_whisper_cpp': True,
                'language': 'en',
                'device': 'cpu',
                'beam_size': 5
            },
            'diarization': {
                'model_id': 'pyannote/speaker-diarization-3.1',
                'auth_token_env': ['HF_TOKEN', 'HUGGINGFACE_TOKEN']
            }
        },
        'speaker_identification': {
            'embedding_model_id': 'pyannote/wespeaker-voxceleb-resnet34-LM',
            'auth_token_env': ['HF_TOKEN', 'HUGGINGFACE_TOKEN'],
            'device': 'cpu',
            'prefer_mps_on_mac': False,
            'similarity_threshold': 0.68
        },
        'speakers': {
            'known_speakers': {}
        },
        'concurrency': {
            'validation_workers': 2,
            'transcription_workers': 2,
            'merge_workers': 2
        },
        'logging': {
            'log_dir': 'logs',
            'log_level': 'INFO'
        }
    }


@pytest.fixture
def temp_dir():
    """Provide a temporary directory that is cleaned up after the test."""
    temp_path = tempfile.mkdtemp()
    yield Path(temp_path)
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def temp_output_dir(temp_dir):
    """Create temporary output directory structure."""
    output_dir = temp_dir / "output"
    output_dir.mkdir()
    (output_dir / "merged_videos").mkdir()
    (output_dir / "transcripts").mkdir()
    (output_dir / "speaker_voice_samples").mkdir()
    (output_dir / "repaired_cache").mkdir()
    return output_dir


# ============================================================================
# Test Data Fixtures
# ============================================================================

@pytest.fixture
def sample_video_clips():
    """
    Provide sample video clip metadata for testing.

    Returns a list of clip dictionaries with typical structure.
    """
    base_time = datetime(2025, 10, 15, 10, 0, 0)

    return [
        {
            'camera': 'FrontDoor',
            'datetime': base_time,
            'path': '/fake/path/08-37-43_FrontDoorG123_001.mp4',
            'full_path': '/fake/path/08-37-43_FrontDoorG123_001.mp4',
            'duration': 30.0
        },
        {
            'camera': 'Corner',
            'datetime': base_time + timedelta(seconds=5),
            'path': '/fake/path/08-37-48_CornerG456_001.mp4',
            'full_path': '/fake/path/08-37-48_CornerG456_001.mp4',
            'duration': 28.0
        },
        {
            'camera': 'Backyard',
            'datetime': base_time + timedelta(seconds=10),
            'path': '/fake/path/08-37-53_BackyardG789_001.mp4',
            'full_path': '/fake/path/08-37-53_BackyardG789_001.mp4',
            'duration': 25.0
        }
    ]


@pytest.fixture
def sample_transcript():
    """Provide sample transcript data for testing."""
    return [
        {
            'start': 0.0,
            'end': 3.5,
            'text': 'Hello everyone, welcome to the meeting.',
            'speaker': 'speaker_0001'
        },
        {
            'start': 4.0,
            'end': 7.2,
            'text': 'Thanks for joining us today.',
            'speaker': 'speaker_0002'
        },
        {
            'start': 8.0,
            'end': 12.5,
            'text': "Let's get started with the first item on the agenda.",
            'speaker': 'speaker_0001'
        }
    ]


# ============================================================================
# Mock Fixtures for External Dependencies
# ============================================================================

@pytest.fixture
def mock_torch():
    """Mock PyTorch for testing without requiring actual installation."""
    torch = MagicMock()
    torch.cuda.is_available.return_value = False
    torch.backends.mps.is_available.return_value = False
    torch.device.return_value = MagicMock()
    torch.set_float32_matmul_precision = MagicMock()

    sys.modules['torch'] = torch
    yield torch

    if 'torch' in sys.modules:
        del sys.modules['torch']


@pytest.fixture
def mock_transformers():
    """Mock transformers library for testing."""
    transformers = MagicMock()

    # Mock pipeline
    mock_pipeline_instance = MagicMock()
    mock_pipeline_instance.return_value = [
        {'label': 'person', 'score': 0.95},
        {'label': 'person', 'score': 0.87}
    ]
    transformers.pipeline.return_value = mock_pipeline_instance

    sys.modules['transformers'] = transformers
    yield transformers

    if 'transformers' in sys.modules:
        del sys.modules['transformers']


@pytest.fixture
def mock_vision_framework():
    """Mock Apple Vision framework for testing."""
    Vision = MagicMock()
    Quartz = MagicMock()

    # Mock Vision request and results
    mock_observation = MagicMock()
    mock_observation.confidence = 0.9
    mock_observation.boundingBox = MagicMock()

    mock_request = MagicMock()
    mock_request.results.return_value = [mock_observation, mock_observation]

    Vision.VNDetectHumanRectanglesRequest.return_value = mock_request
    Vision.VNImageRequestHandler.return_value = MagicMock()

    sys.modules['Vision'] = Vision
    sys.modules['Quartz'] = Quartz
    sys.modules['Quartz.CIImage'] = Quartz.CIImage

    yield Vision, Quartz

    for mod in ['Vision', 'Quartz', 'Quartz.CIImage']:
        if mod in sys.modules:
            del sys.modules[mod]


@pytest.fixture
def mock_pyannote():
    """Mock pyannote.audio for testing speaker identification."""
    pyannote = MagicMock()
    pyannote_audio = MagicMock()

    # Mock Model
    mock_model = MagicMock()
    pyannote_audio.Model.from_pretrained.return_value = mock_model

    # Mock Inference
    mock_inference = MagicMock()
    mock_inference.to.return_value = mock_inference

    import numpy as np
    mock_inference.return_value = np.random.rand(1, 512).astype(np.float32)

    pyannote_audio.Inference.return_value = mock_inference

    sys.modules['pyannote'] = pyannote
    sys.modules['pyannote.audio'] = pyannote_audio

    yield pyannote, pyannote_audio

    for mod in ['pyannote', 'pyannote.audio']:
        if mod in sys.modules:
            del sys.modules[mod]


@pytest.fixture
def mock_env_tokens(monkeypatch):
    """Set up mock environment tokens for HuggingFace."""
    monkeypatch.setenv('HF_TOKEN', 'test_token_123')
    monkeypatch.setenv('HUGGINGFACE_TOKEN', 'test_token_123')


# ============================================================================
# Utility Functions
# ============================================================================

def create_mock_video_file(path: Path, duration: float = 10.0) -> Path:
    """
    Create a minimal mock video file for testing.

    Note: This doesn't create a real video, just a file marker.
    Tests requiring actual video files should use @pytest.mark.requires_video_files.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path
