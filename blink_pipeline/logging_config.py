"""
Comprehensive logging configuration for the video processing pipeline.

Provides file-based logging with rotation, structured formatting, and
separate handlers for different log levels.
"""

import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone as tz
from pathlib import Path


class ExcludePatternsFilter(logging.Filter):
    """Filter out records containing any of the given substrings, unless level >= ERROR."""
    def __init__(self, patterns: list[str] | None = None, allow_errors: bool = True):
        super().__init__()
        self.patterns = patterns or []
        self.allow_errors = allow_errors
    def filter(self, record: logging.LogRecord) -> bool:
        if self.allow_errors and record.levelno >= logging.ERROR:
            return True
        try:
            msg = record.getMessage()
        except Exception:
            return True
        for p in self.patterns:
            if p and p in msg:
                return False
        return True


class PipelineLogger:
    """
    Configures comprehensive file-based logging for the pipeline.

    Creates multiple log files:
    - pipeline.log: All logs (DEBUG and above)
    - pipeline_errors.log: Errors and critical issues only
    - pipeline_<timestamp>.log: Session-specific log (for archival)
    """

    def __init__(self, log_dir: str = "logs", log_level: str = "INFO", session_log_level: str | None = None, suppress_patterns: list[str] | None = None):
        """
        Initialize pipeline logging.

        Args:
            log_dir: Directory for log files
            log_level: Minimum log level for main rotating log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            session_log_level: Level for the session log file; defaults to log_level
            suppress_patterns: Substrings to suppress in file logs (e.g., ['[MONITOR]', '[PROGRESS]'])
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Convert log level strings to logging constants
        self.log_level = getattr(logging, log_level.upper(), logging.INFO)
        if isinstance(session_log_level, str):
            self.session_log_level = getattr(logging, session_log_level.upper(), self.log_level)
        else:
            self.session_log_level = self.log_level

        # Patterns to suppress in file logs (errors always pass)
        self.suppress_patterns = list(suppress_patterns or ["[MONITOR]", "[PROGRESS]"])

        # Session identifier for archival logs
        self.session_id = datetime.now(tz.utc).strftime("%Y%m%d_%H%M%S")

        # Configure root logger
        self._configure_root_logger()

    # No stored logger instance; use logging.getLogger("pipeline") directly

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
        # Suppress chatty monitor/progress messages unless they are errors
        if self.suppress_patterns:
            main_handler.addFilter(ExcludePatternsFilter(self.suppress_patterns))
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
        session_handler.setLevel(self.session_log_level)
        session_handler.setFormatter(detailed_formatter)
        if self.suppress_patterns:
            session_handler.addFilter(ExcludePatternsFilter(self.suppress_patterns))
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
        logging.getLogger("pipeline").info("=" * 80)
        logging.getLogger("pipeline").info("PIPELINE SESSION STARTED: %s", self.session_id)
        logging.getLogger("pipeline").info("=" * 80)
        logging.getLogger("pipeline").info("Log directory: %s", self.log_dir.absolute())
        logging.getLogger("pipeline").info("Log level: %s", logging.getLevelName(self.log_level))
        logging.getLogger("pipeline").info("Python version: %s", sys.version)
        logging.getLogger("pipeline").info("Working directory: %s", os.getcwd())

        # Log key configuration
        logging.getLogger("pipeline").info("Configuration:")
        logging.getLogger("pipeline").info("  Input directory: %s", config['paths']['input_dir'])
        logging.getLogger("pipeline").info("  Output directory: %s", config['paths']['output_dir'])
        logging.getLogger("pipeline").info("  Max time diff: %ss", config['grouping']['max_time_diff_seconds'])
        logging.getLogger("pipeline").info("  Transcription workers: %s", config.get('concurrency', {}).get('transcription_workers', 'auto'))
        logging.getLogger("pipeline").info("  Merge workers: %s", config.get('concurrency', {}).get('merge_workers', 'auto'))

    def log_session_end(self, success: bool = True):
        """Log session end."""
        logging.getLogger("pipeline").info("=" * 80)
        if success:
            logging.getLogger("pipeline").info("PIPELINE SESSION COMPLETED SUCCESSFULLY: %s", self.session_id)
        else:
            logging.getLogger("pipeline").error("PIPELINE SESSION FAILED: %s", self.session_id)
        logging.getLogger("pipeline").info("=" * 80)

    def log_stage_start(self, stage_name: str, stage_number: int, details: str = ""):
        """Log the start of a pipeline stage."""
        logging.getLogger("pipeline").info("-" * 80)
        logging.getLogger("pipeline").info("STAGE %d: %s - START", stage_number, stage_name)
        if details:
            logging.getLogger("pipeline").info("  %s", details)
        logging.getLogger("pipeline").info("-" * 80)

    def log_stage_end(self, stage_name: str, stage_number: int, success: bool = True, details: str = ""):
        """Log the end of a pipeline stage."""
        status = "COMPLETE" if success else "FAILED"
        logging.getLogger("pipeline").info("-" * 80)
        logging.getLogger("pipeline").info("STAGE %d: %s - %s", stage_number, stage_name, status)
        if details:
            logging.getLogger("pipeline").info("  %s", details)
        logging.getLogger("pipeline").info("-" * 80)

    def log_worker_start(self, worker_type: str, worker_id: str, details: str = ""):
        """Log worker process start."""
        logging.getLogger("pipeline.worker.%s" % worker_type).debug("Worker %s started - %s", worker_id, details)

    def log_worker_end(self, worker_type: str, worker_id: str, success: bool = True, details: str = ""):
        """Log worker process end."""
        if success:
            logging.getLogger("pipeline.worker.%s" % worker_type).debug("Worker %s completed - %s", worker_id, details)
        else:
            logging.getLogger("pipeline.worker.%s" % worker_type).error("Worker %s failed - %s", worker_id, details)

    def log_exception(self, context: str, exc: Exception):
        """Log an exception with full traceback."""
        logging.getLogger("pipeline").error("Exception in %s: %s: %s", context, type(exc).__name__, exc, exc_info=True)
        logging.getLogger("pipeline").error(
            "Exception in %s: %s: %s", context, type(exc).__name__, exc, exc_info=exc
        )

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
    log_cfg = config.get('logging', {}) or {}
    log_dir = log_cfg.get('log_dir', 'logs')
    log_level = log_cfg.get('log_level', 'INFO')
    session_log_level = log_cfg.get('session_log_level', log_level)
    suppress_patterns = log_cfg.get('suppress_patterns', ["[MONITOR]", "[PROGRESS]"])

    # Create and configure logger
    pipeline_logger = PipelineLogger(
        log_dir=log_dir,
        log_level=log_level,
        session_log_level=session_log_level,
        suppress_patterns=suppress_patterns,
    )

    # Log session start
    pipeline_logger.log_session_start(config)

    return pipeline_logger


def configure_worker_logging(log_dir: str = "logs", log_level: str = "INFO", suppress_patterns: list[str] | None = None):
    """
    Configure logging for worker processes.

    This should be called at the start of each worker function to ensure
    logs from workers are captured to files (not just suppressed to console).

    Args:
        log_dir: Directory for log files
        log_level: Minimum log level for worker file handler
        suppress_patterns: Substrings to suppress (e.g., ['[MONITOR]', '[PROGRESS]']); errors always pass
    """
    # Get or create root logger
    root_logger = logging.getLogger()

    # Remove console handlers (Rich interferes with stderr)
    root_logger.handlers = [h for h in root_logger.handlers if not isinstance(h, logging.StreamHandler)]

    # Ensure we have file handlers
    if not any(isinstance(h, (logging.FileHandler, logging.handlers.RotatingFileHandler)) for h in root_logger.handlers):
        # Add file handler if it doesn't exist
        log_path = Path(log_dir) / "pipeline.log"
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setLevel(getattr(logging, (log_level or "INFO").upper(), logging.INFO))
        formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(processName)-12s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        if suppress_patterns:
            file_handler.addFilter(ExcludePatternsFilter(list(suppress_patterns)))
        else:
            # Default suppression for chatty monitor/progress lines
            file_handler.addFilter(ExcludePatternsFilter(["[MONITOR]", "[PROGRESS]"]))
        root_logger.addHandler(file_handler)
    else:
        # Update existing file handlers to respect level and filters
        for h in root_logger.handlers:
            if isinstance(h, (logging.FileHandler, logging.handlers.RotatingFileHandler)):
                h.setLevel(getattr(logging, (log_level or "INFO").upper(), logging.INFO))
                h.filters = [f for f in h.filters if not isinstance(f, ExcludePatternsFilter)]
                patterns = list(suppress_patterns) if suppress_patterns else ["[MONITOR]", "[PROGRESS]"]
                h.addFilter(ExcludePatternsFilter(patterns))

    # Root logger can remain at DEBUG; handlers decide emission
    root_logger.setLevel(logging.DEBUG)
