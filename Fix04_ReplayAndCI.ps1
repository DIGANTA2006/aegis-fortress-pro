#Requires -Version 5.1
<#
.SYNOPSIS
    Fix 04 â€” Real ReplayEngine + hardened CI pipeline.

.DESCRIPTION
    Two fixes in one script:

    A) tests/replay/replay_engine.py
       Replaces the one-liner that only does f.readlines() with a proper
       tick-replay engine that:
         - Deserializes JSONL or CSV tick files
         - Replays ticks in chronological order with optional speed multiplier
         - Feeds each tick to a strategy callback (backtest integration)
         - Records replay metrics (ticks replayed, elapsed, throughput)

    B) .github/workflows/ci.yml
       Hardens the CI pipeline to also:
         - Check for UTF-8 BOM (the encoding bug this project already had)
         - Run all test folders (unit, stress, integration, load, failover)
         - Cache pip dependencies for faster builds
         - Upload pytest results as a CI artifact

.PARAMETER ProjectRoot
    Path to the aegis_v2 directory.
#>

param(
    [string]$ProjectRoot = $PSScriptRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function P([string]$rel) { Join-Path $ProjectRoot $rel }
function Write-Step([string]$msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK([string]$msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function WriteFile([string]$rel, [string]$content) {
    $full = P $rel
    [System.IO.File]::WriteAllText($full, $content, [System.Text.UTF8Encoding]::new($false))
    Write-OK $rel
}

if (-not (Test-Path $ProjectRoot)) { Write-Error "Project root not found: $ProjectRoot"; exit 1 }
Write-Host "Project root: $ProjectRoot" -ForegroundColor Yellow

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# A. tests/replay/__init__.py  (needed for pytest discovery)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "tests/replay/__init__.py"
$initPath = P "tests\replay\__init__.py"
if (-not (Test-Path $initPath)) {
    [System.IO.File]::WriteAllText($initPath, "", [System.Text.UTF8Encoding]::new($false))
    Write-OK "created"
} else {
    Write-Host "  [--] already exists" -ForegroundColor DarkGray
}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# B. tests/replay/replay_engine.py  â€” full implementation
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "tests/replay/replay_engine.py"

WriteFile "tests\replay\replay_engine.py" @'
"""
tests/replay/replay_engine.py  -  AEGIS PRO v2

Tick-data replay engine for backtesting and integration testing.

Supported file formats
----------------------
  JSONL  â€” one JSON object per line, e.g.:
              {"ts": 1700000000, "symbol": "BTC/USDT", "price": 45000.0, "volume": 1.2}
  CSV    â€” header row required; columns: ts, symbol, price, volume
              ts,symbol,price,volume
              1700000000,BTC/USDT,45000.0,1.2

Usage
-----
    engine = ReplayEngine(speed=0.0)   # speed=0 â†’ instant (no wall-clock delay)
    engine.load("data/ticks.jsonl")
    engine.run(callback=my_strategy.on_tick)
    print(engine.stats())
"""

import csv
import json
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tick data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True, order=True)
class Tick:
    """Single market tick â€” immutable and sortable by timestamp."""
    ts:     float          # Unix timestamp (seconds, float)
    symbol: str
    price:  float
    volume: float
    raw:    dict = field(default_factory=dict, compare=False, hash=False)

    @classmethod
    def from_dict(cls, d: dict) -> "Tick":
        return cls(
            ts=float(d["ts"]),
            symbol=str(d["symbol"]),
            price=float(d["price"]),
            volume=float(d.get("volume", 0.0)),
            raw=d,
        )


# ---------------------------------------------------------------------------
# ReplayEngine
# ---------------------------------------------------------------------------

class ReplayEngine:
    """
    Loads a tick file and replays ticks to a callback in time order.

    Parameters
    ----------
    speed : float
        Replay speed multiplier relative to real time.
        0.0  â†’ replay as fast as possible (no sleep, for backtests).
        1.0  â†’ real-time replay.
        10.0 â†’ 10Ã— faster than real time.
    """

    SUPPORTED_EXTENSIONS = {".jsonl", ".json", ".csv"}

    def __init__(self, speed: float = 0.0):
        if speed < 0:
            raise ValueError("speed must be >= 0")
        self.speed   = speed
        self._ticks: list[Tick] = []

        # Stats
        self._ticks_replayed = 0
        self._start_time: float | None = None
        self._end_time:   float | None = None

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self, path: str | Path) -> int:
        """
        Load and parse a tick file.  Returns the number of ticks loaded.

        Parameters
        ----------
        path : str | Path
            Path to a ``.jsonl`` or ``.csv`` file.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Tick file not found: {p}")
        if p.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {p.suffix}. "
                f"Expected one of {self.SUPPORTED_EXTENSIONS}"
            )

        raw_ticks = list(self._parse(p))
        self._ticks = sorted(raw_ticks)        # chronological order
        log.info("ReplayEngine: loaded %d ticks from %s", len(self._ticks), p)
        return len(self._ticks)

    def load_ticks(self, path: str | Path) -> list[str]:
        """
        Legacy compatibility shim â€” loads the file and returns raw lines.
        Prefer ``load()`` for new code.
        """
        p = Path(path)
        with open(p, "r", encoding="utf-8") as fh:
            return fh.readlines()

    # ------------------------------------------------------------------
    # Replay
    # ------------------------------------------------------------------

    def run(self, callback: Callable[[Tick], None]) -> None:
        """
        Replay all loaded ticks, calling *callback* for each one.

        Parameters
        ----------
        callback : Callable[[Tick], None]
            Receives one ``Tick`` at a time, in chronological order.
            Exceptions raised inside the callback are caught and logged;
            replay continues.
        """
        if not self._ticks:
            log.warning("ReplayEngine.run: no ticks loaded â€” call load() first")
            return

        self._ticks_replayed = 0
        self._start_time     = time.monotonic()
        prev_tick_ts: float | None = None

        for tick in self._ticks:
            if self.speed > 0 and prev_tick_ts is not None:
                gap     = tick.ts - prev_tick_ts
                sleep_s = gap / self.speed
                if sleep_s > 0:
                    time.sleep(sleep_s)

            try:
                callback(tick)
            except Exception:
                log.exception(
                    "ReplayEngine: callback raised on tick ts=%.3f symbol=%s",
                    tick.ts, tick.symbol,
                )

            self._ticks_replayed += 1
            prev_tick_ts = tick.ts

        self._end_time = time.monotonic()
        log.info(
            "ReplayEngine: replayed %d ticks in %.3fs (%.0f ticks/s)",
            self._ticks_replayed,
            self.elapsed,
            self.throughput,
        )

    def iter_ticks(self) -> Iterator[Tick]:
        """Yield ticks one at a time without a callback (generator interface)."""
        yield from self._ticks

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def elapsed(self) -> float:
        if self._start_time is None or self._end_time is None:
            return 0.0
        return self._end_time - self._start_time

    @property
    def throughput(self) -> float:
        """Ticks per second during last replay."""
        if self.elapsed == 0:
            return float("inf")
        return self._ticks_replayed / self.elapsed

    def stats(self) -> dict:
        return {
            "ticks_loaded":   len(self._ticks),
            "ticks_replayed": self._ticks_replayed,
            "elapsed_s":      round(self.elapsed, 4),
            "throughput_tps": round(self.throughput, 1) if self.elapsed > 0 else None,
            "speed_factor":   self.speed,
        }

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse(self, p: Path) -> Iterator[Tick]:
        if p.suffix.lower() in {".jsonl", ".json"}:
            yield from self._parse_jsonl(p)
        elif p.suffix.lower() == ".csv":
            yield from self._parse_csv(p)

    @staticmethod
    def _parse_jsonl(p: Path) -> Iterator[Tick]:
        with open(p, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    yield Tick.from_dict(d)
                except (json.JSONDecodeError, KeyError, ValueError) as exc:
                    log.warning("ReplayEngine: skipping line %d â€” %s", lineno, exc)

    @staticmethod
    def _parse_csv(p: Path) -> Iterator[Tick]:
        with open(p, "r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for lineno, row in enumerate(reader, 2):   # 2 = first data row
                try:
                    yield Tick.from_dict(row)
                except (KeyError, ValueError) as exc:
                    log.warning("ReplayEngine: skipping CSV row %d â€” %s", lineno, exc)
'@

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# C. tests/replay/test_replay_engine.py  â€” unit tests
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "tests/replay/test_replay_engine.py"

WriteFile "tests\replay\test_replay_engine.py" @'
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
'@

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# D. .github/workflows/ci.yml  â€” hardened pipeline
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step ".github/workflows/ci.yml"

WriteFile ".github\workflows\ci.yml" @'
name: AEGIS-CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      # â”€â”€ Checkout â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
      - uses: actions/checkout@v4

      # â”€â”€ Python â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
      - name: Set up Python 3.10
        uses: actions/setup-python@v5
        with:
          python-version: "3.10"

      # â”€â”€ Cache pip â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
      - name: Cache pip
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}
          restore-keys: ${{ runner.os }}-pip-

      # â”€â”€ Dependencies â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install -r requirements.txt

      # â”€â”€ BOM check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
      # Catch UTF-8 BOM (U+FEFF) before it reaches Python
      - name: Check for UTF-8 BOM
        run: |
          echo "Scanning for BOM-infected Python files..."
          bad=$(grep -rlP '^\xEF\xBB\xBF' --include="*.py" . || true)
          if [ -n "$bad" ]; then
            echo "::error::BOM found in: $bad"
            exit 1
          fi
          echo "No BOM issues found."

      # â”€â”€ Lint: Ruff â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
      - name: Ruff lint
        run: ruff check .

      # â”€â”€ Lint: Black â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
      - name: Black format check
        run: black --check .

      # â”€â”€ Tests â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
      - name: Run all tests
        run: |
          pytest tests/ \
            --tb=short \
            --junitxml=test-results.xml \
            -v

      # â”€â”€ Upload test results â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: pytest-results
          path: test-results.xml
'@

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# E. Update pytest.ini to discover all test folders
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "pytest.ini"

WriteFile "pytest.ini" @'
[pytest]
testpaths   = tests
python_files = test_*.py
addopts     = -v --tb=short
'@

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Done
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Host "`n=================================================" -ForegroundColor Magenta
Write-Host "  Fix 04 complete â€” ReplayEngine + CI done." -ForegroundColor Magenta
Write-Host "  Next: run Fix05_StructuredLogging.ps1" -ForegroundColor Magenta
Write-Host "=================================================" -ForegroundColor Magenta
