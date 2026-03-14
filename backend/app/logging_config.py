"""
Logging configuration for Vestige.

Sets up structlog with:
  - Coloured, human-readable console output (dev)
  - JSON output to a rotating log file (logs/vestige.log)
  - An in-memory ring buffer of the last N log lines for the /api/system/logs endpoint
  - Log level controllable via LOG_LEVEL env var (default: INFO)

Call configure_logging() once at startup (from main.py).
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import json
import collections
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

AEST = timezone(timedelta(hours=10), "AEST")


def _aest_timestamper(logger, method, event_dict):
    event_dict["timestamp"] = datetime.now(tz=AEST).isoformat()
    return event_dict

import structlog

# ── Ring buffer for UI log tail ────────────────────────────────────────────

LOG_RING_SIZE = 500
_ring: collections.deque[dict] = collections.deque(maxlen=LOG_RING_SIZE)
_ring_lock = threading.Lock()


def get_recent_logs(n: int = 100, level: str | None = None) -> list[dict]:
    """Return the last n log entries, optionally filtered by minimum level."""
    LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
    min_level = LEVELS.get((level or "").upper(), 0)
    with _ring_lock:
        entries = list(_ring)
    if min_level:
        entries = [e for e in entries if LEVELS.get(e.get("level", "INFO").upper(), 20) >= min_level]
    return entries[-n:]


class _RingHandler(logging.Handler):
    """Appends formatted log records to the in-memory ring buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=AEST).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        with _ring_lock:
            _ring.append(entry)


# ── Setup ──────────────────────────────────────────────────────────────────

def configure_logging() -> None:
    debug_mode = os.environ.get("DEBUG_MODE", "false").lower() in ("true", "1", "yes")
    if debug_mode:
        log_level_name = "DEBUG"
    else:
        log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    # ── Log file ──────────────────────────────────────────────────────────
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "vestige.log"

    # ── Handlers ──────────────────────────────────────────────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    # This formatter is overridden below by the structlog ProcessorFormatter,
    # but set a sensible fallback anyway.

    ring_handler = _RingHandler()
    console_handler = logging.StreamHandler(sys.stdout)

    # ── Root logger ───────────────────────────────────────────────────────
    root = logging.getLogger()
    root.setLevel(log_level)
    # Remove any existing handlers (uvicorn may have added some)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(ring_handler)
    root.addHandler(console_handler)

    # In debug mode: allow all loggers through; otherwise suppress noisy ones
    if not debug_mode:
        for noisy in ("uvicorn.access", "httpx", "httpcore"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    # ── structlog ─────────────────────────────────────────────────────────
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            _aest_timestamper,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also route structlog output through the ring buffer by binding a stdlib bridge
    # structlog → stdlib bridge so ring_handler captures structlog events too
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            _aest_timestamper,
            structlog.processors.StackInfoRenderer(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()),
        ],
    )
    console_handler.setFormatter(formatter)

    file_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    file_handler.setFormatter(file_formatter)
