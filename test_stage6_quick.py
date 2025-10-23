#!/usr/bin/env python3
"""Quick test of Stage 6 transcription on one video."""

import yaml
import logging
from pathlib import Path
from blink_pipeline.whisper_cpp_wrapper import WhisperCppWrapper

# Setup logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')

# Load config
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Get whisper config
whisper_config = config['transcription']['whisper']
model_path = whisper_config['ggml_model_path']
binary = whisper_config.get('whisper_cpp_binary')
language = whisper_config.get('language', 'en')

print(f"Model: {model_path}")
print(f"Binary: {binary}")
print(f"Language: {language}")

# Create wrapper
wrapper = WhisperCppWrapper(
    model_path=model_path,
    whisper_cpp_binary=binary,
    device='auto'
)

# Test with our test audio
print("\n=== Testing transcription on test_audio.wav ===")
result = wrapper.transcribe('test_audio.wav', language=language)

print(f"\nLanguage: {result['language']}")
print(f"Segments: {len(result['segments'])}")
print(f"\nFull text: {result['text']}")
print("\nSegments:")
for seg in result['segments'][:5]:
    print(f"  [{seg['start']:.1f}s -> {seg['end']:.1f}s] {seg['text']}")
