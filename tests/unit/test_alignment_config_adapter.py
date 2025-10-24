"""
Alignment config adapter tests

Ensures AlignmentEngine accepts Pydantic AlignmentConfig from
blink_pipeline.composition.config and correctly maps aliased fields.
"""
from pathlib import Path
from unittest.mock import patch

import numpy as np

from blink_pipeline.composition.alignment import AlignmentEngine
from blink_pipeline.composition.config import AlignmentConfig as PydanticAlignmentConfig


def make_engine():
    # Use non-default values to verify alias mapping is applied
    pcfg = PydanticAlignmentConfig(
        enabled=True,
        max_shift_seconds=0.5,
        analysis_window_seconds=0.5,
        sample_rate=22050,
        bandpass=True,
        highpass_hz=100.0,
        lowpass_hz=5000.0,
        estimate_drift=False,
    )
    return AlignmentEngine(pcfg)


@patch('librosa.load')
@patch('blink_pipeline.composition.alignment.ensure_wav_cache')
def test_extract_audio_uses_pydantic_config_aliases(mock_wav_cache, mock_load, tmp_path):
    engine = make_engine()

    dummy_wav = str(tmp_path / 'dummy.wav')
    mock_wav_cache.return_value = dummy_wav

    # librosa.load returns zeros and we capture kwargs for assertions
    captured = {}

    def fake_load(path, **kwargs):
        captured.update(kwargs)
        sr = kwargs.get('sr') or 22050
        return np.zeros(100, dtype=np.float32), sr

    mock_load.side_effect = fake_load

    arr = engine._extract_audio_segment(Path('cam1.mp4'))

    assert arr is not None
    # Verify sample rate came from Pydantic config
    assert captured.get('sr') == 22050


@patch('librosa.load')
@patch('blink_pipeline.composition.alignment.ensure_wav_cache')
def test_align_clips_with_pydantic_config(mock_wav_cache, mock_load, tmp_path):
    engine = make_engine()

    # Create consistent test audio at 22.05 kHz
    fs = 22050
    duration = 1.0
    t = np.linspace(0, duration, int(fs * duration), endpoint=False)
    ref_audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)

    # Camera audio with small delay
    delay_samples = int(0.02 * fs)
    cam_audio = np.zeros_like(ref_audio)
    cam_audio[delay_samples:] = ref_audio[:-delay_samples]

    # Provide deterministic wav path for each video path
    def fake_wav_cache(path, *args, **kwargs):
        name = Path(path).stem
        return str(tmp_path / f"{name}.wav")

    mock_wav_cache.side_effect = fake_wav_cache

    # librosa returns cam_audio for cam1 and ref_audio for ref, matching fs
    def fake_load(path, **kwargs):
        sr = kwargs.get('sr') or fs
        if 'cam1' in str(path):
            return cam_audio, sr
        return ref_audio, sr

    mock_load.side_effect = fake_load

    camera_clips = {
        'ref': [Path('ref_001.mp4')],
        'cam1': [Path('cam1_001.mp4')],
    }

    results = engine.align_clips(camera_clips, ref_camera='ref')

    assert len(results) == 1
    assert results[0].camera == 'cam1'
    # Offset should be reasonable (within max_shift_seconds)
    assert abs(results[0].offset_seconds) <= 0.5
