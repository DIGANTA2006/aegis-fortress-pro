"""Unit tests for configs/__init__.py Ã¢â‚¬â€ YAML loader and env override."""

import os
import tempfile
import pytest
from pathlib import Path
from configs import load_yaml_config, _cast, _set_nested


# ---------------------------------------------------------------------------
# _cast helper
# ---------------------------------------------------------------------------

def test_cast_int():      assert _cast("42")    == 42
def test_cast_float():    assert _cast("3.14")  == pytest.approx(3.14)
def test_cast_true():     assert _cast("true")  is True
def test_cast_false():    assert _cast("false") is False
def test_cast_string():   assert _cast("hello") == "hello"


# ---------------------------------------------------------------------------
# _set_nested helper
# ---------------------------------------------------------------------------

def test_set_nested_single_key():
    d = {}
    _set_nested(d, ["x"], 99)
    assert d == {"x": 99}

def test_set_nested_deep():
    d = {}
    _set_nested(d, ["a", "b", "c"], "deep")
    assert d["a"]["b"]["c"] == "deep"


# ---------------------------------------------------------------------------
# load_yaml_config with a temp file
# ---------------------------------------------------------------------------

SAMPLE_YAML = """
exchange:
  primary: binance
  timeout_seconds: 10

monitoring:
  metrics_port: 9090
"""

def _write_yaml(content: str) -> Path:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    f.write(content)
    f.close()
    return Path(f.name)


def test_load_yaml_reads_values():
    path = _write_yaml(SAMPLE_YAML)
    cfg  = load_yaml_config(path)
    assert cfg["exchange"]["primary"]       == "binance"
    assert cfg["monitoring"]["metrics_port"] == 9090


def test_load_yaml_missing_file_returns_empty():
    cfg = load_yaml_config("/no/such/file.yaml")
    assert cfg == {}


def test_env_override_string(monkeypatch):
    path = _write_yaml(SAMPLE_YAML)
    monkeypatch.setenv("AEGIS_EXCHANGE__PRIMARY", "kraken")
    cfg = load_yaml_config(path)
    assert cfg["exchange"]["primary"] == "kraken"


def test_env_override_int(monkeypatch):
    path = _write_yaml(SAMPLE_YAML)
    monkeypatch.setenv("AEGIS_MONITORING__METRICS_PORT", "9091")
    cfg = load_yaml_config(path)
    assert cfg["monitoring"]["metrics_port"] == 9091


def test_env_override_creates_new_key(monkeypatch):
    path = _write_yaml(SAMPLE_YAML)
    monkeypatch.setenv("AEGIS_TRADING__DEFAULT_SYMBOL", "ETH/USDT")
    cfg = load_yaml_config(path)
    assert cfg["trading"]["default_symbol"] == "ETH/USDT"