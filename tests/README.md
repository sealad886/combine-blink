# Test Suite Documentation

## Overview

The combine-blink project uses pytest for all automated testing. Tests are organized into unit tests, integration tests, and manual tests.

## Test Structure

```
tests/
├── conftest.py                      # Shared fixtures and configuration
├── test_identify_speaker_unit.py    # Speaker identification unit tests
├── test_whisper_cpp_integration.py  # Whisper.cpp integration tests
├── unit/                            # Unit tests (fast, no external deps)
│   ├── test_av_alignment.py
│   ├── test_discovery.py
│   ├── test_grouping.py
│   └── test_people_detection.py
├── integration/                     # Integration tests (require external services)
│   └── test_media_validation.py
└── manual/                          # Manual/visual tests (require human review)
```

## Running Tests

### Run all tests
```bash
pytest
```

### Run only unit tests (fast)
```bash
pytest -m unit
```

### Run only integration tests
```bash
pytest -m integration
```

### Run tests excluding slow tests
```bash
pytest -m "not slow"
```

### Run with verbose output
```bash
pytest -v
```

### Run specific test file
```bash
pytest tests/unit/test_grouping.py
```

### Run specific test class or function
```bash
pytest tests/unit/test_grouping.py::TestVideoGrouping::test_single_camera_single_clip
```

## Test Markers

Tests are marked with pytest markers for categorization:

- `@pytest.mark.unit`: Fast unit tests with no external dependencies
- `@pytest.mark.integration`: Integration tests requiring external services
- `@pytest.mark.slow`: Tests that take >1 second to run
- `@pytest.mark.requires_ffmpeg`: Tests requiring ffmpeg
- `@pytest.mark.requires_models`: Tests requiring ML models downloaded
- `@pytest.mark.requires_video_files`: Tests requiring actual video files
- `@pytest.mark.manual`: Tests requiring manual review

## Shared Fixtures

Common fixtures are defined in `conftest.py`:

### Configuration Fixtures
- `base_config`: Minimal valid configuration for testing
- `temp_dir`: Temporary directory cleaned up after test
- `temp_output_dir`: Temporary output directory structure

### Mock Fixtures
- `mock_torch`: Mock PyTorch for testing without installation
- `mock_transformers`: Mock transformers library
- `mock_vision_framework`: Mock Apple Vision framework
- `mock_pyannote`: Mock pyannote.audio for speaker identification
- `mock_env_tokens`: Set up mock HuggingFace tokens

### Data Fixtures
- `sample_video_clips`: Sample video clip metadata
- `sample_transcript`: Sample transcript data

## Test Coverage by Module

### ✅ Fully Tested (Unit + Integration)
- `blink_pipeline.grouping`: Multi-camera grouping logic
- `blink_pipeline.identify_speaker`: Speaker identification
- `blink_pipeline.people_detection`: People detection backends
- `blink_pipeline.transcription`: Whisper integration and config
- `blink_pipeline.discovery`: Filename parsing and date detection
- `blink_pipeline.media_validation`: Progress file operations

### ⚠️ Partially Tested (Unit only, integration requires real data)
- `blink_pipeline.av_alignment`: Audio alignment configuration
- `blink_pipeline.media_utils`: Video repair strategies (interface tested)

### ❌ Not Tested (Complex mocking required)
These modules require extensive mocking of external processes (ffmpeg, ML models)
or real video files for meaningful tests:

- `blink_pipeline.video`: FFmpeg video operations (requires real ffmpeg)
- `blink_pipeline.multi_camera_composer`: Full composition pipeline
- `blink_pipeline.orchestrator`: Pipeline orchestration
- `blink_pipeline.pipeline_dashboard`: Rich console dashboard
- `blink_pipeline.progress`: Progress tracking with multiprocessing

**Rationale for exclusion**: These modules are tightly coupled to:
- FFmpeg subprocess execution with complex filter graphs
- Large ML model loading (Whisper, pyannote)
- Real-time progress tracking with multiprocessing
- File I/O operations on actual video files

Testing these properly would require:
- Mock video generation (prohibitively complex)
- End-to-end integration tests with real hardware
- Manual validation of visual output

## Manual Testing

Some functionality cannot be easily automated and requires manual testing:

### Visual/UI Components (`manual/` directory)
- Dashboard rendering and progress display
- Timing display and ETA calculations
- Log formatting and output

### Performance Testing
- Actual video repair performance benchmarks
- Multi-camera composition performance
- Hardware acceleration validation (VideoToolbox, MPS, Neural Engine)

### Real-World Integration
- Full pipeline runs with real Blink video clusters
- Multi-hour processing sessions
- Resume capability under various failure modes

To run manual tests:
```bash
python tests/manual/test_dashboard.py
python tests/manual/test_progress.py
python tests/manual/test_logging.py
```

## Writing New Tests

### Unit Test Template
```python
import pytest


@pytest.mark.unit
class TestMyModule:
    """Test suite for my_module."""

    def test_basic_functionality(self):
        """Test basic functionality."""
        from blink_pipeline.my_module import my_function

        result = my_function(input_data)

        assert result == expected_output

    @pytest.mark.parametrize("input,expected", [
        ("case1", "output1"),
        ("case2", "output2"),
    ])
    def test_multiple_cases(self, input, expected):
        """Test multiple cases."""
        from blink_pipeline.my_module import my_function

        result = my_function(input)
        assert result == expected
```

### Integration Test Template
```python
import pytest


@pytest.mark.integration
@pytest.mark.requires_ffmpeg
class TestMyIntegration:
    """Integration tests for my_module."""

    def test_with_external_dependency(self, temp_dir):
        """Test with external dependency."""
        from blink_pipeline.my_module import process_video

        result = process_video(input_path, str(temp_dir))

        assert result is not None
```

## Continuous Integration

To integrate with CI/CD:

```yaml
# Example GitHub Actions workflow
- name: Run tests
  run: |
    pytest -m "unit" --tb=short
    pytest -m "integration and not requires_video_files" --tb=short
```

## Troubleshooting

### Tests fail with import errors
Ensure the project is installed in development mode:
```bash
pip install -e .
```

### Tests fail with missing dependencies
Install test dependencies:
```bash
pip install pytest pytest-mock
```

### Slow test execution
Run only fast unit tests:
```bash
pytest -m "unit and not slow"
```

### Debugging test failures
Run with verbose output and show local variables:
```bash
pytest -vv --tb=long --showlocals
```

## Code Coverage

To generate coverage report (requires pytest-cov):
```bash
pip install pytest-cov
pytest --cov=blink_pipeline --cov-report=html --cov-report=term
```

View HTML report:
```bash
open htmlcov/index.html
```

## Best Practices

1. **Keep unit tests fast**: Unit tests should run in <100ms each
2. **Use fixtures for reusable data**: Define fixtures in conftest.py
3. **Mark tests appropriately**: Use markers to categorize tests
4. **Test edge cases**: Include boundary conditions and error cases
5. **Use parametrize for similar tests**: Avoid code duplication
6. **Mock external dependencies**: Use mocks for APIs, file I/O, subprocesses
7. **Document limitations**: Add comments explaining what can't be tested
8. **Skip gracefully**: Use pytest.skip() for tests requiring unavailable resources

## Contributing

When adding new features:

1. Write unit tests for core logic
2. Write integration tests for external interactions (if feasible)
3. Document any manual testing requirements
4. Update this documentation with new test markers or fixtures
5. Ensure tests pass before submitting PR:
   ```bash
   pytest -m "unit"
   ```
