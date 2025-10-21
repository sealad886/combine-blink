import numpy as np
from src.av_alignment import gcc_phat


def test_gcc_phat_basic_delay():
    fs = 16000
    rng = np.random.default_rng(0)
    ref = rng.standard_normal(fs // 2).astype(np.float32)
    delay_s = 0.035  # 35 ms
    shift = int(round(delay_s * fs))
    sig = np.concatenate([np.zeros(shift, dtype=np.float32), ref])

    # Use equal-length windows
    n = min(len(ref), len(sig))
    tau = gcc_phat(sig[:n], ref[:n], fs=fs, max_tau=0.1)

    # Should be within a few ms (coarse sanity check)
    assert abs(tau - delay_s) < 0.01


if __name__ == "__main__":
    test_gcc_phat_basic_delay()
    print("gcc_phat basic test passed")
