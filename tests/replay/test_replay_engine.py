"""Unit tests for the ReplayEngine."""

import json
import csv
import tempfile
import pytest
from pathlib import Path
from tests.replay.replay_engine import ReplayEngine, Tick


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_TICKS = [
    {"ts": 1_700_000_100, "symbol": "BTC/USDT", "price": 45_100.0, "volume": 0.5},
    {"ts": 1_700_000_000, "symbol": "BTC/USDT", "price": 45_000.0, "volume": 1.2},
    {"ts": 1_700_000_200, "symbol": "BTC/USDT", "price": 45_200.0, "volume": 0.8},
]


def _write_jsonl(ticks: list[dict]) -> Path:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    )
    for t in ticks:
        f.write(json.dumps(t) + "\n")
    f.close()
    return Path(f.name)


def _write_csv(ticks: list[dict]) -> Path:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
    )
    writer = csv.DictWriter(f, fieldnames=["ts", "symbol", "price", "volume"])
    writer.writeheader()
    writer.writerows(ticks)
    f.close()
    return Path(f.name)


# ---------------------------------------------------------------------------
# Load tests
# ---------------------------------------------------------------------------

def test_load_jsonl_count():
    path   = _write_jsonl(SAMPLE_TICKS)
    engine = ReplayEngine()
    count  = engine.load(path)
    assert count == 3


def test_load_csv_count():
    path   = _write_csv(SAMPLE_TICKS)
    engine = ReplayEngine()
    count  = engine.load(path)
    assert count == 3


def test_load_sorts_chronologically():
    path   = _write_jsonl(SAMPLE_TICKS)  # deliberately unsorted
    engine = ReplayEngine()
    engine.load(path)
    tss = [t.ts for t in engine.iter_ticks()]
    assert tss == sorted(tss)


def test_load_missing_file_raises():
    engine = ReplayEngine()
    with pytest.raises(FileNotFoundError):
        engine.load("/nonexistent/file.jsonl")


def test_load_unsupported_extension_raises():
    engine = ReplayEngine()
    with pytest.raises(ValueError, match="Unsupported"):
        engine.load("data.parquet")


# ---------------------------------------------------------------------------
# Replay tests
# ---------------------------------------------------------------------------

def test_run_calls_callback_for_each_tick():
    path    = _write_jsonl(SAMPLE_TICKS)
    engine  = ReplayEngine(speed=0.0)
    engine.load(path)

    received = []
    engine.run(callback=received.append)

    assert len(received) == 3


def test_run_delivers_ticks_in_order():
    path   = _write_jsonl(SAMPLE_TICKS)
    engine = ReplayEngine(speed=0.0)
    engine.load(path)

    received = []
    engine.run(callback=received.append)

    assert received[0].ts < received[1].ts < received[2].ts


def test_run_callback_exception_does_not_abort():
    """A bad callback should not stop the rest of the replay."""
    path   = _write_jsonl(SAMPLE_TICKS)
    engine = ReplayEngine(speed=0.0)
    engine.load(path)

    calls = []
    def flaky(tick):
        calls.append(tick)
        if len(calls) == 2:
            raise RuntimeError("simulated error")

    engine.run(callback=flaky)
    assert len(calls) == 3     # all 3 delivered despite error on #2


def test_stats_after_run():
    path   = _write_jsonl(SAMPLE_TICKS)
    engine = ReplayEngine(speed=0.0)
    engine.load(path)
    engine.run(callback=lambda t: None)

    s = engine.stats()
    assert s["ticks_loaded"]   == 3
    assert s["ticks_replayed"] == 3
    assert s["elapsed_s"]      >= 0


def test_run_no_ticks_loaded_is_safe():
    engine = ReplayEngine()
    engine.run(callback=lambda t: None)   # should not raise
    assert engine.stats()["ticks_replayed"] == 0


def test_tick_from_dict():
    t = Tick.from_dict({"ts": "1700000000", "symbol": "ETH/USDT", "price": "3000", "volume": "2.5"})
    assert t.ts     == 1_700_000_000.0
    assert t.symbol == "ETH/USDT"
    assert t.price  == 3_000.0


def test_legacy_load_ticks_returns_lines():
    path   = _write_jsonl(SAMPLE_TICKS)
    engine = ReplayEngine()
    lines  = engine.load_ticks(path)
    assert len(lines) == 3
    assert isinstance(lines[0], str)