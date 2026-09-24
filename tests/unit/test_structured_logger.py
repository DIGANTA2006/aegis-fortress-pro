"""Unit tests for core/structured_logger.py"""

import json
import logging
import io
import pytest

from core.structured_logger import (
    JsonFormatter,
    configure_logger,
    correlation_id,
    get_correlation_id,
    set_correlation_id,
)


# ---------------------------------------------------------------------------
# JsonFormatter
# ---------------------------------------------------------------------------

def _capture_log(level=logging.DEBUG) -> tuple[logging.Logger, io.StringIO]:
    buf     = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logger  = logging.getLogger(f"test.{id(buf)}")
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger, buf


def test_json_formatter_basic_fields():
    logger, buf = _capture_log()
    logger.info("hello world")
    record = json.loads(buf.getvalue().strip())
    assert record["message"] == "hello world"
    assert record["level"]   == "INFO"
    assert "timestamp" in record
    assert "logger"    in record


def test_json_formatter_includes_correlation_id():
    logger, buf = _capture_log()
    with correlation_id("test-cid-123"):
        logger.warning("processing")
    record = json.loads(buf.getvalue().strip())
    assert record["correlation_id"] == "test-cid-123"


def test_json_formatter_no_correlation_id_by_default():
    set_correlation_id(None)
    logger, buf = _capture_log()
    logger.info("no id")
    record = json.loads(buf.getvalue().strip())
    assert "correlation_id" not in record


def test_json_formatter_exception():
    logger, buf = _capture_log()
    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("caught error")
    record = json.loads(buf.getvalue().strip())
    assert "exc_info"  in record
    assert "ValueError" in record["exc_info"]


# ---------------------------------------------------------------------------
# correlation_id context manager
# ---------------------------------------------------------------------------

def test_correlation_id_set_and_clear():
    set_correlation_id(None)
    with correlation_id("abc"):
        assert get_correlation_id() == "abc"
    assert get_correlation_id() is None


def test_correlation_id_nested():
    with correlation_id("outer"):
        with correlation_id("inner"):
            assert get_correlation_id() == "inner"
        assert get_correlation_id() == "outer"
    assert get_correlation_id() is None


def test_correlation_id_restored_on_exception():
    set_correlation_id(None)
    try:
        with correlation_id("cid-restore"):
            raise RuntimeError("error inside")
    except RuntimeError:
        pass
    assert get_correlation_id() is None


# ---------------------------------------------------------------------------
# configure_logger
# ---------------------------------------------------------------------------

def test_configure_logger_sets_json_handler():
    configure_logger(level=logging.WARNING)
    root = logging.getLogger()
    assert any(
        isinstance(h.formatter, JsonFormatter)
        for h in root.handlers
    )