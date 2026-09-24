"""
tests/replay/replay_engine.py  -  AEGIS PRO v2

Tick-data replay engine for backtesting and integration testing.

Supported file formats
----------------------
  JSONL  ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â one JSON object per line, e.g.:
              {"ts": 1700000000, "symbol": "BTC/USDT", "price": 45000.0, "volume": 1.2}
  CSV    ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â header row required; columns: ts, symbol, price, volume
              ts,symbol,price,volume
              1700000000,BTC/USDT,45000.0,1.2

Usage
-----
    engine = ReplayEngine(speed=0.0)   # speed=0 ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ instant (no wall-clock delay)
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
    """Single market tick ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â immutable and sortable by timestamp."""
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
        0.0  ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ replay as fast as possible (no sleep, for backtests).
        1.0  ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ real-time replay.
        10.0 ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ 10ÃƒÆ’Ã¢â‚¬â€ faster than real time.
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
        if p.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {p.suffix}. "
                f"Expected one of {self.SUPPORTED_EXTENSIONS}"
            )
        if not p.exists():
            raise FileNotFoundError(f"Tick file not found: {p}")

        raw_ticks = list(self._parse(p))
        self._ticks = sorted(raw_ticks)        # chronological order
        log.info("ReplayEngine: loaded %d ticks from %s", len(self._ticks), p)
        return len(self._ticks)

    def load_ticks(self, path: str | Path) -> list[str]:
        """
        Legacy compatibility shim ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â loads the file and returns raw lines.
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
            log.warning("ReplayEngine.run: no ticks loaded ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â call load() first")
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
                    log.warning("ReplayEngine: skipping line %d ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â %s", lineno, exc)

    @staticmethod
    def _parse_csv(p: Path) -> Iterator[Tick]:
        with open(p, "r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for lineno, row in enumerate(reader, 2):   # 2 = first data row
                try:
                    yield Tick.from_dict(row)
                except (KeyError, ValueError) as exc:
                    log.warning("ReplayEngine: skipping CSV row %d ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â %s", lineno, exc)