"""
Audio Processing Module

Audio cleanup, normalization, and crossfading utilities for the modular
composition pipeline. This module focuses on building robust and explicit
FFmpeg filter graphs for audio processing, so the rest of the pipeline
can remain IO-efficient and avoid unnecessary decoding/encoding cycles.

Classes:
- AudioProcessor: Main audio processing engine (filter graph builder)

Author: Phase 4 implementation
Status: Initial implementation (cleanup builder + acrossfade chain)
"""

import numpy as np

from typing import Iterable, Sequence, Tuple, Optional, List

from .config import AudioCleanupConfig, AudioMixConfig


class AudioProcessor:
    """Audio processing for cleanup, normalization, and crossfading.

    This class does not perform PCM-domain processing. Instead, it builds
    FFmpeg filter strings that the composer can use in single-pass or
    staged pipelines. This keeps CPU and IO overhead low.
    """

    # Valid curve names per FFmpeg afade/acrossfade docs
    _VALID_CURVES = {
        'tri', 'qsin', 'hsin', 'esin', 'log', 'ipar', 'qua', 'cub', 'squ',
        'cbr', 'par', 'exp', 'iqsin', 'ihsin', 'dese', 'desi', 'losi',
        'sinc', 'isinc', 'quat', 'quatr', 'qsin2', 'hsin2', 'nofade'
    }

    def __init__(self, cleanup: Optional[AudioCleanupConfig] = None, mix: Optional[AudioMixConfig] = None):
        """Initialize processor with configuration blocks.

        Parameters:
            cleanup: Audio cleanup configuration
            mix: Audio mixing/crossfade configuration
        """
        self.cleanup = cleanup or AudioCleanupConfig()
        self.mix = mix or AudioMixConfig()

    # ----------------------- Cleanup filter chain -----------------------
    def build_cleanup_filter(self) -> Optional[str]:
        """Build FFmpeg audio cleanup filter chain.

        Returns a comma-separated filter chain string (or None if disabled).
        The chain mirrors options supported by AudioCleanupConfig using
        highpass/lowpass, afftdn, and loudnorm filters.
        """
        if not getattr(self.cleanup, 'enabled', True):
            return None

        filters: List[str] = []
        if self.cleanup.highpass_hz and self.cleanup.highpass_hz > 0:
            filters.append(f"highpass=f={self.cleanup.highpass_hz:g}")
        if self.cleanup.lowpass_hz and self.cleanup.lowpass_hz > 0:
            filters.append(f"lowpass=f={self.cleanup.lowpass_hz:g}")
        if getattr(self.cleanup, 'denoise', True):
            nf = getattr(self.cleanup, 'denoise_nf', -25.0)
            filters.append(f"afftdn=nf={float(nf):g}")
        if getattr(self.cleanup, 'loudness_normalize', True):
            I = float(getattr(self.cleanup, 'loudnorm_target_i', -23.0))
            TP = float(getattr(self.cleanup, 'loudnorm_target_tp', -2.0))
            LRA = float(getattr(self.cleanup, 'loudnorm_target_lra', 11.0))
            filters.append(f"loudnorm=I={I:g}:TP={TP:g}:LRA={LRA:g}:dual_mono=true")
        extra = getattr(self.cleanup, 'extra_filters', None) or []
        for f in extra:
            if f:
                filters.append(str(f))

        return ','.join(filters) if filters else None

    def apply_cleanup(
        self,
        audio: np.ndarray,
        sample_rate: int
    ) -> np.ndarray:
        """Apply audio cleanup filters."""
        raise NotImplementedError("Phase 4 implementation pending")

    def crossfade(
        self,
        audio1: np.ndarray,
        audio2: np.ndarray,
        duration: float,
        sample_rate: int
    ) -> np.ndarray:
        """Crossfade between two audio segments."""
        raise NotImplementedError("Phase 4 implementation pending")

    def normalize_loudness(
        self,
        audio: np.ndarray,
        sample_rate: int
    ) -> np.ndarray:
        """Normalize audio loudness."""
        raise NotImplementedError("Phase 4 implementation pending")

    # ----------------------- Crossfade filter chain ----------------------
    def build_acrossfade_chain(
        self,
        input_labels: Sequence[str],
        duration: Optional[float] = None,
        curve1: Optional[str] = None,
        curve2: Optional[str] = None,
        overlap: Optional[bool] = None,
        output_label: str = 'aout',
    ) -> Tuple[str, str]:
        """Build an FFmpeg filter chain to acrossfade a sequence of inputs.

        Parameters:
            input_labels: List of labels for input streams (e.g., ['0:a','1:a',...]
                           or intermediate labels like ['a0','a1',...])
            duration: Crossfade duration in seconds; defaults to mix.crossfade_seconds
            curve1: Curve for outgoing stream; defaults to mix.curve1
            curve2: Curve for incoming stream; defaults to mix.curve2
            overlap: Whether to overlap streams; defaults to mix.overlap
            output_label: Label name for final output from the chain

        Returns:
            (filters, out_label) where filters is a semicolon-separated string
            of filtergraph steps, and out_label is the label name with output.

        Notes:
            - When len(input_labels) <= 1, a concat graph (no fades) is returned.
            - The implementation uses a ladder of acrossfade filters for explicit control.
        """
        n = len(input_labels)
        if n == 0:
            return ("", output_label)
        if n == 1:
            # No processing needed; map straight through
            single = input_labels[0]
            return (f"[{single}]anull[{output_label}]", output_label)

        # Resolve parameters with config defaults
        d = float(duration if duration is not None else max(0.0, float(self.mix.crossfade_seconds)))
        # Constrain to a reasonable range to avoid unexpected long fades
        d = max(0.0, min(5.0, d))
        c1 = (curve1 or self.mix.curve1 or 'tri').lower()
        c2 = (curve2 or self.mix.curve2 or 'tri').lower()
        if c1 not in self._VALID_CURVES:
            c1 = 'tri'
        if c2 not in self._VALID_CURVES:
            c2 = 'tri'
        o = overlap if overlap is not None else bool(self.mix.overlap)

        # Ducking parameters
        use_duck = bool(getattr(self.mix, 'ducking_enabled', False))
        duck_thr = float(getattr(self.mix, 'ducking_threshold', 0.125))
        duck_ratio = float(getattr(self.mix, 'ducking_ratio', 2.0))
        duck_attack = float(getattr(self.mix, 'ducking_attack_ms', 20.0))
        duck_release = float(getattr(self.mix, 'ducking_release_ms', 250.0))
        duck_makeup = float(getattr(self.mix, 'ducking_makeup', 1.0))

        # Build ladder: [a0][a1]acrossfade -> [a01], [a01][a2]acrossfade -> ...
        filters: List[str] = []
        # Pick base label for first pair
        first_out = 'a01'
        o_flag = 1 if o else 0
        # Optional sidechain ducking: compress outgoing (left) by incoming (right)
        left = input_labels[0]
        right = input_labels[1]
        if use_duck:
            duck_lbl = 'd01'
            filters.append(
                f"[{left}][{right}]sidechaincompress=threshold={duck_thr:g}:ratio={duck_ratio:g}:attack={duck_attack:g}:release={duck_release:g}:makeup={duck_makeup:g}[{duck_lbl}]"
            )
            left = duck_lbl
        filters.append(
            f"[{left}][{right}]acrossfade=d={d}:o={o_flag}:c1={c1}:c2={c2}[{first_out}]"
        )

        last = first_out
        if n > 2:
            for i in range(2, n):
                nxt = f"a0{i}"
                right = input_labels[i]
                left = last
                if use_duck:
                    duck_lbl = f"d0{i}"
                    filters.append(
                        f"[{left}][{right}]sidechaincompress=threshold={duck_thr:g}:ratio={duck_ratio:g}:attack={duck_attack:g}:release={duck_release:g}:makeup={duck_makeup:g}[{duck_lbl}]"
                    )
                    left = duck_lbl
                filters.append(
                    f"[{left}][{right}]acrossfade=d={d}:o={o_flag}:c1={c1}:c2={c2}[{nxt}]"
                )
                last = nxt

        # Final rename to requested output label
        filters.append(f"[{last}]anull[{output_label}]")
        return ('; '.join(filters), output_label)


__all__ = ['AudioProcessor']
