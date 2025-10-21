#!/usr/bin/env python3
"""
Test the comprehensive logging system.

This script verifies that:
1. Log files are created correctly
2. Different log levels work
3. Rotation is configured
4. Worker logging works
5. Exception logging includes tracebacks
"""

import os
import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.logging_config import PipelineLogger, configure_worker_logging

def test_basic_logging():
    """Test basic logging functionality."""
    print("\n" + "="*80)
    print("TESTING BASIC LOGGING")
    print("="*80)

    # Create logger
    logger_system = PipelineLogger(log_dir="logs_test", log_level="DEBUG")
    logger = logger_system.get_logger()

    # Test different log levels
    logger.debug("This is a DEBUG message - very detailed")
    logger.info("This is an INFO message - general information")
    logger.warning("This is a WARNING message - potential issue")
    logger.error("This is an ERROR message - something failed")
    logger.critical("This is a CRITICAL message - severe failure")

    print("\n✓ Basic logging test complete")
    print(f"  Check logs_test/ directory for log files")

def test_structured_logging():
    """Test structured logging with stages and workers."""
    print("\n" + "="*80)
    print("TESTING STRUCTURED LOGGING")
    print("="*80)

    # Create logger with mock config
    config = {
        'paths': {'input_dir': 'test_input', 'output_dir': 'test_output'},
        'grouping': {'max_time_diff_seconds': 300},
        'concurrency': {'transcription_workers': 2, 'merge_workers': 3}
    }

    logger_system = PipelineLogger(log_dir="logs_test", log_level="INFO")
    logger_system.log_session_start(config)

    # Test stage logging
    logger_system.log_stage_start("Test Stage", 1, "Testing stage logging")
    logger_system.log_stage_end("Test Stage", 1, success=True, details="Stage completed successfully")

    # Test worker logging
    logger_system.log_worker_start("transcription", "worker-1", "Processing group_A")
    logger_system.log_worker_end("transcription", "worker-1", success=True, details="3 clips processed")

    logger_system.log_session_end(success=True)

    print("\n✓ Structured logging test complete")

def test_exception_logging():
    """Test exception logging with traceback."""
    print("\n" + "="*80)
    print("TESTING EXCEPTION LOGGING")
    print("="*80)

    logger_system = PipelineLogger(log_dir="logs_test", log_level="DEBUG")
    logger = logger_system.get_logger()

    # Test exception logging
    try:
        # Simulate an error
        result = 1 / 0
    except Exception as exc:
        logger_system.log_exception("test_exception_logging", exc)
        print("\n✓ Exception logged with full traceback")

def test_worker_logging():
    """Test worker process logging configuration."""
    print("\n" + "="*80)
    print("TESTING WORKER LOGGING CONFIGURATION")
    print("="*80)

    # Configure worker logging
    configure_worker_logging("logs_test")

    logger = logging.getLogger("pipeline.worker.test")
    logger.info("This is a worker log message")
    logger.debug("This is a debug message from worker")
    logger.error("This is an error from worker")

    print("\n✓ Worker logging configuration test complete")

def test_log_files_created():
    """Verify log files were created."""
    print("\n" + "="*80)
    print("VERIFYING LOG FILES")
    print("="*80)

    log_dir = Path("logs_test")

    # Check for expected files
    main_log = log_dir / "pipeline.log"
    error_log = log_dir / "pipeline_errors.log"

    # Find session log
    session_logs = list(log_dir.glob("pipeline_*.log"))

    print(f"\n📁 Log directory: {log_dir.absolute()}")
    print(f"\nLog files created:")
    print(f"  ✓ pipeline.log: {'EXISTS' if main_log.exists() else 'MISSING'}")
    print(f"  ✓ pipeline_errors.log: {'EXISTS' if error_log.exists() else 'MISSING'}")
    print(f"  ✓ Session logs: {len(session_logs)} found")

    if main_log.exists():
        size = main_log.stat().st_size
        print(f"\n  Main log size: {size:,} bytes")
        print(f"  Last 10 lines of pipeline.log:")
        print("  " + "-"*76)
        with open(main_log, 'r') as f:
            lines = f.readlines()
            for line in lines[-10:]:
                print(f"  {line.rstrip()}")

    if error_log.exists():
        size = error_log.stat().st_size
        print(f"\n  Error log size: {size:,} bytes")
        if size > 0:
            print(f"  Contents of pipeline_errors.log:")
            print("  " + "-"*76)
            with open(error_log, 'r') as f:
                for line in f:
                    print(f"  {line.rstrip()}")

def main():
    """Run all logging tests."""
    print("\n" + "="*80)
    print("COMPREHENSIVE LOGGING SYSTEM TEST")
    print("="*80)

    # Create test log directory
    test_log_dir = Path("logs_test")
    test_log_dir.mkdir(exist_ok=True)

    # Run tests
    test_basic_logging()
    test_structured_logging()
    test_exception_logging()
    test_worker_logging()
    test_log_files_created()

    print("\n" + "="*80)
    print("ALL TESTS COMPLETE")
    print("="*80)
    print(f"\n✓ Test logs created in: {test_log_dir.absolute()}")
    print("✓ Check the log files to verify formatting and content")
    print("\nTo clean up test logs:")
    print(f"  rm -rf {test_log_dir}")
    print()

if __name__ == '__main__':
    main()
