"""Tests for pipelines.logging_config module."""
import json
import logging

from pipelines.logging_config import get_logger


def test_get_logger_returns_logger():
    log = get_logger("test.module")
    assert isinstance(log, logging.Logger)
    assert log.name == "test.module"


def test_get_logger_idempotent():
    log1 = get_logger("test.idempotent")
    log2 = get_logger("test.idempotent")
    assert log1 is log2
    assert len(log1.handlers) == 1


def test_text_formatter_output(capsys, monkeypatch):
    monkeypatch.setenv("HCDW_LOG_FORMAT", "text")
    name = "test.text_format"
    logging.getLogger(name).handlers.clear()
    log = get_logger(name)
    log.info("hello world")
    captured = capsys.readouterr()
    assert "hello world" in captured.err
    assert "INFO" in captured.err


def test_json_formatter_output(capsys, monkeypatch):
    monkeypatch.setenv("HCDW_LOG_FORMAT", "json")
    name = "test.json_format"
    logging.getLogger(name).handlers.clear()
    log = get_logger(name)
    log.info("json test", extra={"layer": "bronze", "rows_written": 42})
    captured = capsys.readouterr()
    record = json.loads(captured.err.strip())
    assert record["msg"] == "json test"
    assert record["level"] == "INFO"
    assert record["layer"] == "bronze"
    assert record["rows_written"] == 42
    assert "ts" in record


def test_log_level_respected(capsys, monkeypatch):
    monkeypatch.setenv("HCDW_LOG_FORMAT", "text")
    monkeypatch.setenv("HCDW_LOG_LEVEL", "WARNING")
    name = "test.level_filter"
    logging.getLogger(name).handlers.clear()
    log = get_logger(name)
    log.info("should not appear")
    log.warning("should appear")
    captured = capsys.readouterr()
    assert "should not appear" not in captured.err
    assert "should appear" in captured.err
