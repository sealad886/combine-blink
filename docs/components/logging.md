# Logging Architecture

Logging is configured by `blink_pipeline/logging_config.py` and activated at the start of
`blink_pipeline/orchestrator.py`. It is entirely file-based to avoid clashing with Rich’s
terminal output.

## PipelineLogger

`setup_pipeline_logging(config)` creates a `PipelineLogger` instance which:

- Ensures `log_dir` exists (default `logs/`).
- Configures the root logger with the following handlers:
  1. **Rotating main log** — `pipeline.log`, max 10 MB × 10 files, level = configured `log_level`.
  2. **Rotating errors** — `pipeline_errors.log`, max 5 MB × 5 files, level = `ERROR`.
  3. **Session log** — `pipeline_{timestamp}.log`, level = configured `session_log_level` (default `INFO`) for a single run.
- Optionally a console handler can be enabled for warnings/errors (disabled by
  default to keep the terminal clean while Rich is active).

Session metadata (paths, worker counts, Python version) is recorded via
`log_session_start`, and a symmetric `log_session_end` prints success/failure
bookends.

## Worker Logging

Each worker process calls `configure_worker_logging(log_dir)`:

- Removes console handlers (Rich already owns stderr).
- Ensures at least one file handler is attached (reusing the main log).
- Sets level to `INFO` by default (configurable) and suppresses chatty `[PROGRESS]`/`[MONITOR]` lines.

Worker loggers use namespaces like `pipeline.transcription` and `pipeline.merge`
for clarity.

## Log Format

```
2025-10-21 10:46:07 | INFO     | ForkPoolWorker-1 | pipeline.transcription:process_audio_for_transcription:82 | Starting transcription for group: 20251015_104607_Entry
```

Components:

- Timestamp (`%Y-%m-%d %H:%M:%S`)
- Level (padded to 8 characters)
- Process name (`MainProcess`, `ForkPoolWorker-3`, etc.)
- Logger name, function, and line
- Message

## Configuration

```yaml
logging:
  log_dir: logs
  log_level: INFO           # DEBUG/INFO/WARNING/ERROR/CRITICAL (main rotating log)
  session_log_level: INFO   # Per-run session log level; defaults to log_level
  suppress_patterns:        # Suppress non-error lines containing these substrings
    - "[MONITOR]"
    - "[PROGRESS]"
```

- `log_level` affects the main rotating log (`pipeline.log`).
- `session_log_level` controls the per-run archival log; default is `INFO`.
- `suppress_patterns` drops matching records from file logs unless they are errors.

## Usage Tips

- Tail error logs live: `tail -f logs/pipeline_errors.log`.
- Filter by group name: `rg "group_name" logs/pipeline.log`.
- Clean session logs periodically: `find logs -name 'pipeline_*.log' -mtime +7 -delete`.

## Tests

- `test_logging.py`: validates handler configuration, rotation sizes, and helper
  methods.

When adjusting logging, run this test and confirm new handlers follow the same
structure to keep downstream tooling stable.

## Design Simplification

We removed redundant module- and instance-level `logger` variables across the codebase.
Instead of storing `logger = ...` in modules or classes, code now calls `logging.getLogger(...)`
inline where needed (for example, `logging.getLogger("pipeline").info(...)`).

- This avoids confusion between the standard Python logger and the `PipelineLogger` helper.
- `PipelineLogger.get_logger(name)` is retained for backward compatibility, but new code should prefer
  direct `logging.getLogger(name)` calls.
- Worker tasks and subsystems use namespaced loggers like `pipeline.transcription`, `pipeline.merge`,
  or the module name (e.g. `blink_pipeline.composition.quality`).
