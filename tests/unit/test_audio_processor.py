import re

from blink_pipeline.composition.audio import AudioProcessor
from blink_pipeline.composition.config import AudioCleanupConfig, AudioMixConfig


def test_build_cleanup_filter_default_chain_includes_expected_filters():
    cfg = AudioCleanupConfig(
        enabled=True,
        highpass_hz=100.0,
        lowpass_hz=5000.0,
        denoise=True,
        denoise_nf=-30.0,
        loudness_normalize=True,
        loudnorm_target_i=-23.0,
        loudnorm_target_tp=-2.0,
        loudnorm_target_lra=11.0,
    )
    ap = AudioProcessor(cleanup=cfg)
    chain = ap.build_cleanup_filter()
    assert chain is not None
    # Ensure individual filters are present and ordered
    assert 'highpass=f=100' in chain
    assert 'lowpass=f=5000' in chain
    assert 'afftdn=nf=-30' in chain
    assert 'loudnorm=I=-23' in chain


def test_build_acrossfade_chain_two_inputs_default_tri_and_overlap_enabled():
    mix = AudioMixConfig(crossfade_seconds=0.1, curve1='tri', curve2='tri', overlap=True)
    ap = AudioProcessor(mix=mix)
    filters, out = ap.build_acrossfade_chain(['0:a', '1:a'])
    assert out == 'aout'
    # Expect acrossfade with duration, overlap flag, and curves
    assert 'acrossfade' in filters
    assert 'd=0.1' in filters
    assert 'o=1' in filters
    assert 'c1=tri' in filters and 'c2=tri' in filters


def test_build_acrossfade_chain_three_inputs_ladder_and_output_label():
    mix = AudioMixConfig(crossfade_seconds=0.05, curve1='log', curve2='exp', overlap=False)
    ap = AudioProcessor(mix=mix)
    filters, out = ap.build_acrossfade_chain(['a0', 'a1', 'a2'], output_label='final')
    assert out == 'final'
    # First pair -> a01, then a01 with a2 -> a02, then rename to final via anull
    assert '[a0][a1]acrossfade' in filters
    assert 'o=0' in filters
    assert 'c1=log' in filters and 'c2=exp' in filters
    # Ensure last step maps to final label
    assert re.search(r"\[a0[0-9]\]anull\[final\]", filters) is not None


def test_build_acrossfade_chain_two_inputs_with_ducking_inserts_sidechaincompress():
    mix = AudioMixConfig(
        crossfade_seconds=0.12,
        curve1='tri',
        curve2='tri',
        overlap=True,
        ducking_enabled=True,
        ducking_threshold=0.2,
        ducking_ratio=3.0,
        ducking_attack_ms=15.0,
        ducking_release_ms=200.0,
        ducking_makeup=1.2,
    )
    ap = AudioProcessor(mix=mix)
    filters, out = ap.build_acrossfade_chain(['0:a', '1:a'])
    assert out == 'aout'
    # sidechaincompress should precede the acrossfade and use configured params
    assert '[0:a][1:a]sidechaincompress=' in filters
    assert 'threshold=0.2' in filters
    assert 'ratio=3' in filters
    assert 'attack=15' in filters
    assert 'release=200' in filters
    assert 'makeup=1.2' in filters
    # Acrossfade should use ducked left label feeding into incoming right
    assert '[d01][1:a]acrossfade' in filters


def test_build_acrossfade_chain_three_inputs_with_ducking_ladder_ducks_each_stage():
    mix = AudioMixConfig(
        crossfade_seconds=0.08,
        curve1='log',
        curve2='exp',
        overlap=False,
        ducking_enabled=True,
        ducking_threshold=0.1,
        ducking_ratio=2.5,
        ducking_attack_ms=10.0,
        ducking_release_ms=180.0,
        ducking_makeup=1.0,
    )
    ap = AudioProcessor(mix=mix)
    filters, out = ap.build_acrossfade_chain(['a0', 'a1', 'a2'], output_label='out')
    assert out == 'out'
    # First stage ducking then acrossfade
    assert '[a0][a1]sidechaincompress=' in filters
    assert '[d01][a1]acrossfade' in filters
    # Second stage ducking then acrossfade using previous result
    assert '[a01]' in filters  # intermediate from first acrossfade
    assert '[a01][a2]sidechaincompress=' in filters or '[d02]' in filters
    assert '[d02][a2]acrossfade' in filters
