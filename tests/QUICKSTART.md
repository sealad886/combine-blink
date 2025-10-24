# Test Suite Quick Start

## 🚀 Running Tests

### All Tests (Unit + Integration)
```bash
pytest tests/unit/ tests/integration/ -v
```

### Unit Tests Only (Fast, no external dependencies)
```bash
pytest tests/unit/ -v
# or using markers:
pytest -m unit -v
```

### Integration Tests Only
```bash
pytest tests/integration/ -v
# or using markers:
pytest -m integration -v
```

### Specific Test File
```bash
pytest tests/unit/test_grouping.py -v
```

### Specific Test Function
```bash
pytest tests/unit/test_grouping.py::TestVideoGrouping::test_single_camera_single_clip -v
```

## 📊 Common Options

### Show Test Coverage
```bash
pytest tests/ --cov=blink_pipeline --cov-report=html
# Open htmlcov/index.html in browser
```

### Stop on First Failure
```bash
pytest tests/ -x
```

### Run Last Failed Tests
```bash
pytest --lf
```

### Run Only Changed Files
```bash
pytest --picked
```

### Show Print Statements
```bash
pytest tests/ -v -s
```

### Quiet Mode (Less Verbose)
```bash
pytest tests/ -q
```

## 🏷️ Using Markers

### Skip Slow Tests
```bash
pytest -m "not slow"
```

### Skip Tests Requiring Video Files
```bash
pytest -m "not requires_video_files"
```

### Skip Tests Requiring ML Models
```bash
pytest -m "not requires_models"
```

### Run Only Fast Unit Tests
```bash
pytest -m "unit and not slow"
```

## 📝 Test Results Summary

Current status:
- ✅ **89 tests passing**
- ⏭️ **15 tests skipped** (require video files, ML models, or private APIs)
- ⏱️ **~60 seconds** to run full suite

## 🐛 Debugging Failed Tests

### Show Full Traceback
```bash
pytest tests/ --tb=long
```

### Show Local Variables on Failure
```bash
pytest tests/ -l
```

### Enter Debugger on Failure
```bash
pytest tests/ --pdb
```

### Run with Verbose Output
```bash
pytest tests/ -vv
```

## 📦 Dependencies

Required for all tests:
- pytest >= 7.0
- pytest-mock
- pytest-cov (for coverage reports)

Optional (tests skip gracefully if missing):
- PIL/Pillow (for people_detection tests)
- torch (mocked in unit tests)
- transformers (mocked in unit tests)
- pyannote (mocked in unit tests)

## 💡 Tips

1. **Clear pytest cache if tests behave oddly:**
   ```bash
   pytest --cache-clear tests/
   ```

2. **Clear Python cache:**
   ```bash
   find tests/ -type d -name __pycache__ -exec rm -rf {} +
   ```

3. **Run tests in parallel (if pytest-xdist installed):**
   ```bash
   pytest tests/ -n auto
   ```

4. **Generate JUnit XML for CI:**
   ```bash
   pytest tests/ --junitxml=test-results.xml
   ```

5. **Watch mode (if pytest-watch installed):**
   ```bash
   ptw tests/
   ```

## 📚 More Information

- Full documentation: See `tests/README.md`
- Test results summary: See `TEST_RESULTS.md`
- pytest documentation: https://docs.pytest.org/
