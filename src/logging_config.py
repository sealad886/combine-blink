"""
Comprehensive logging configuration for the video processing pipeline.

Provides file-based logging with rotation, structured formatting, and
separate handlers for different log levels.
"""

import logging
import logging.handlers
import os
import sys
from datetime import datetime
from typing import Optional
from pathlib import Path


class PipelineLogger:
    """
    Configures comprehensive file-based logging for the pipeline.

    Creates multiple log files:
    - pipeline.log: All logs (DEBUG and above)
    - pipeline_errors.log: Errors and critical issues only
    - pipeline_<timestamp>.log: Session-specific log (for archival)
    """

    def __init__(self, log_dir: str = "logs", log_level: str = "INFO"):
        """
        Initialize pipeline logging.

        Args:
            log_dir: Directory for log files
            log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        # Convert log level string to logging constant
        self.log_level = getattr(logging, log_level.upper(), logging.INFO)

        # Session identifier for archival logs
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Configure root logger
        self._configure_root_logger()

        # Get logger instance
        self.logger = logging.getLogger("pipeline")

    def _configure_root_logger(self):
        """Configure the root logger with multiple handlers."""
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)  # Capture everything, filter in handlers

        # Remove any existing handlers to avoid duplicates
        root_logger.handlers.clear()

        # Create formatter with detailed information
        detailed_formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(processName)-12s | %(name)s:%(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # Simple formatter for console (if needed)
        simple_formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%H:%M:%S'
        )

        # 1. Main log file (rotating, keeps last 10 files of 10MB each)
        main_log_path = self.log_dir / "pipeline.log"
        main_handler = logging.handlers.RotatingFileHandler(
            main_log_path,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=10,
            encoding='utf-8'
        )
        main_handler.setLevel(self.log_level)
        main_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(main_handler)

        # 2. Error log file (rotating, keeps last 5 files of 5MB each)
        error_log_path = self.log_dir / "pipeline_errors.log"
        error_handler = logging.handlers.RotatingFileHandler(
            error_log_path,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=5,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(error_handler)

        # 3. Session-specific log (for this run only, not rotating)
        session_log_path = self.log_dir / f"pipeline_{self.session_id}.log"
        session_handler = logging.FileHandler(
            session_log_path,
            encoding='utf-8'
        )
        session_handler.setLevel(logging.DEBUG)  # Capture everything for this session
        session_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(session_handler)

        # 4. Console handler (optional, minimal output to not interfere with Rich)
        # Only show warnings and errors on console
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(simple_formatter)
        # Don't add console handler by default since Rich blocks it
        # root_logger.addHandler(console_handler)

    def log_session_start(self, config: dict):
        """Log session start with configuration details."""
        logger = logging.getLogger("pipeline")
        logger.info("=" * 80)
        logger.info(f"PIPELINE SESSION STARTED: {self.session_id}")
        logger.info("=" * 80)
        logger.info(f"Log directory: {self.log_dir.absolute()}")
        logger.info(f"Log level: {logging.getLevelName(self.log_level)}")
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Working directory: {os.getcwd()}")

        # Log key configuration
        logger.info("Configuration:")
        logger.info(f"  Input directory: {config['paths']['input_dir']}")
        logger.info(f"  Output directory: {config['paths']['output_dir']}")
        logger.info(f"  Max time diff: {config['grouping']['max_time_diff_seconds']}s")
        logger.info(f"  Transcription workers: {config.get('concurrency', {}).get('transcription_workers', 'auto')}")
        logger.info(f"  Merge workers: {config.get('concurrency', {}).get('merge_workers', 'auto')}")

    def log_session_end(self, success: bool = True):
        """Log session end."""
        logger = logging.getLogger("pipeline")
        logger.info("=" * 80)
        if success:
            logger.info(f"PIPELINE SESSION COMPLETED SUCCESSFULLY: {self.session_id}")
        else:
            logger.error(f"PIPELINE SESSION FAILED: {self.session_id}")
        logger.info("=" * 80)

    def log_stage_start(self, stage_name: str, stage_number: int, details: str = ""):
        """Log the start of a pipeline stage."""
        logger = logging.getLogger("pipeline")
        logger.info("-" * 80)
        logger.info(f"STAGE {stage_number}: {stage_name} - START")
        if details:
            logger.info(f"  {details}")
        logger.info("-" * 80)

    def log_stage_end(self, stage_name: str, stage_number: int, success: bool = True, details: str = ""):
        """Log the end of a pipeline stage."""
        logger = logging.getLogger("pipeline")
        status = "COMPLETE" if success else "FAILED"
        logger.info("-" * 80)
        logger.info(f"STAGE {stage_number}: {stage_name} - {status}")
        if details:
            logger.info(f"  {details}")
        logger.info("-" * 80)

    def log_worker_start(self, worker_type: str, worker_id: str, details: str = ""):
        """Log worker process start."""
        logger = logging.getLogger(f"pipeline.worker.{worker_type}")
        logger.debug(f"Worker {worker_id} started - {details}")

    def log_worker_end(self, worker_type: str, worker_id: str, success: bool = True, details: str = ""):
        """Log worker process end."""
        logger = logging.getLogger(f"pipeline.worker.{worker_type}")
        if success:
            logger.debug(f"Worker {worker_id} completed - {details}")
        else:
            logger.error(f"Worker {worker_id} failed - {details}")

    def log_exception(self, context: str, exc: Exception):
        """Log an exception with full traceback."""
        logger = logging.getLogger("pipeline")
        logger.error(f"Exception in {context}: {type(exc).__name__}: {exc}", exc_info=True)

    def get_logger(self, name: str = "pipeline") -> logging.Logger:
        """Get a logger instance."""
        return logging.getLogger(name)


def setup_pipeline_logging(config: dict) -> PipelineLogger:
    """
    Set up comprehensive pipeline logging.

    Args:
        config: Pipeline configuration dictionary

    Returns:
        PipelineLogger instance
    """
    # Get log directory from config or use default
    log_dir = config.get('logging', {}).get('log_dir', 'logs')
    log_level = config.get('logging', {}).get('log_level', 'INFO')

    # Create and configure logger
    pipeline_logger = PipelineLogger(log_dir=log_dir, log_level=log_level)

    # Log session start
    pipeline_logger.log_session_start(config)

    return pipeline_logger


def configure_worker_logging(log_dir: str = "logs"):
    """
    Configure logging for worker processes.

    This should be called at the start of each worker function to ensure
    logs from workers are captured to files (not just suppressed to console).

    Args:
        log_dir: Directory for log files
    """
    # Get or create root logger
    root_logger = logging.getLogger()

    # Remove console handlers (Rich interferes with stderr)
    root_logger.handlers = [h for h in root_logger.handlers if not isinstance(h, logging.StreamHandler)]

    # Ensure we have file handlers
    if not any(isinstance(h, (logging.FileHandler, logging.handlers.RotatingFileHandler)) for h in root_logger.handlers):
        # Add file handlers if they don't exist
        log_path = Path(log_dir) / "pipeline.log"
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(processName)-12s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Set level to DEBUG to capture everything
    root_logger.setLevel(logging.DEBUG)
