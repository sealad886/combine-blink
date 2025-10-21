import os
import sys
import types


def run_check(config, expected_known):
    # Provide a fake token so initialization does not fail on env lookup
    os.environ.setdefault("HF_TOKEN", "dummy")
    os.environ.setdefault("HUGGINGFACE_TOKEN", "dummy")

    # Create fake pyannote.audio modules/classes
    fake_pyannote = types.ModuleType("pyannote")
    fake_audio = types.ModuleType("pyannote.audio")

    class FakeModel:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            return object()

    class FakeInference:
        def __init__(self, model, window="whole"):
            pass
        def to(self, device):
            return self
        def __call__(self, path):
            import numpy as np
            return np.ones((1, 4), dtype=np.float32)

    fake_audio.Inference = FakeInference
    fake_audio.Model = FakeModel

    # Inject fakes
    sys.modules["pyannote"] = fake_pyannote
    sys.modules["pyannote.audio"] = fake_audio

    from src.identify_speaker import SpeakerIdentifier

    si = SpeakerIdentifier(config)
    assert si.known_speakers_map == expected_known

    # name substitution test
    transcript = [
        {"speaker": "speaker_0001", "text": "hello"},
        {"speaker": "speaker_9999", "text": "world"},
    ]
    named = si.substitute_names_in_transcript(transcript)
    if expected_known:
        assert named[0]["speaker"] == expected_known.get("speaker_0001", "speaker_0001")
    else:
        assert named[0]["speaker"] == "speaker_0001"
    assert named[1]["speaker"] == "speaker_9999"


if __name__ == "__main__":
    # Case 1: no speakers mapping
    cfg1 = {
        "paths": {"output_dir": "output", "speakers_dir": "speaker_voice_samples"},
        "speaker_identification": {
            "embedding_model_id": "pyannote/wespeaker-voxceleb-resnet34-LM",
            "auth_token_env": ["HF_TOKEN", "HUGGINGFACE_TOKEN"],
            "device": "cpu",
            "similarity_threshold": 0.9,
        },
    }
    run_check(cfg1, {})

    # Case 2: with speakers mapping
    cfg2 = {
        "paths": {"output_dir": "output", "speakers_dir": "speaker_voice_samples"},
        "speaker_identification": {
            "embedding_model_id": "pyannote/wespeaker-voxceleb-resnet34-LM",
            "auth_token_env": ["HF_TOKEN", "HUGGINGFACE_TOKEN"],
            "device": "cpu",
            "similarity_threshold": 0.9,
        },
        "speakers": {"known_speakers": {"speaker_0001": "Alice"}},
    }
    run_check(cfg2, {"speaker_0001": "Alice"})
    print("identify_speaker basic checks passed.")
