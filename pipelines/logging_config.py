"""Structured logging configuration for all pipeline modules.

Provides a JSON-formatted logger for production use and a human-readable
format for local development. All pipeline modules should use this instead
of print() to stderr.

Usage:
    from pipelines.logging_config import get_logger
    log = get_logger(__name__)
    log.info("loaded rows", extra={"rows": 1000, "source": "patients"})

Set HCDW_LOG_FORMAT=json for JSON output (default in production).
Set HCDW_LOG_FORMAT=text for human-readable output (default locally).
Set HCDW_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR (default: INFO).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line for structured log ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        for key in ("layer", "object_name", "rows_read", "rows_written",
                    "rows_rejected", "source", "run_id", "duration_s"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        return json.dumps(entry, ensure_ascii=False)


class _TextFormatter(logging.Formatter):
    """Human-readable format for local development."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        extra_parts = []
        for key in ("layer", "object_name", "rows_read", "rows_written",
                    "rows_rejected", "source", "run_id"):
            val = getattr(record, key, None)
            if val is not None:
                extra_parts.append(f"{key}={val}")
        extra = f" [{', '.join(extra_parts)}]" if extra_parts else ""
        return f"{ts} {record.levelname:7s} {record.name}: {record.getMessage()}{extra}"


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger for the given module name."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    log_format = os.environ.get("HCDW_LOG_FORMAT", "text").lower()
    log_level = os.environ.get("HCDW_LOG_LEVEL", "INFO").upper()

    handler = logging.StreamHandler(sys.stderr)
    if log_format == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(_TextFormatter())

    logger.addHandler(handler)
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    logger.propagate = False
    return logger
