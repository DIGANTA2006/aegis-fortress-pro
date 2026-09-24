"""
db.py  -  AEGIS PRO v2
SQLite persistence layer with WAL mode, trade journal, equity curve,
position state, and a lightweight tick store.

All connections use WAL (Write-Ahead Logging) for concurrency safety.
"""

import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, List, Optional

from config import PATHS

log = logging.getLogger("aegis.db")


# ---------------------------------------------------------------------------
# Connection factory with WAL mode
# ---------------------------------------------------------------------------


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


# ---------------------------------------------------------------------------
# Main database: trades, performance, equity curve
# ---------------------------------------------------------------------------


class TradeDB:
    """
    Thread-safe SQLite trade journal.
    Uses a single connection protected by a re-entrant lock.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._path = db_path or PATHS["db"]
        self._lock = threading.RLock()
        self._conn = _connect(self._path)
        self._init_schema()

    @contextmanager
    def _cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def _init_schema(self) -> None:
        with self._cursor() as c:
            # ---- Trade log ----
            c.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts          TEXT    NOT NULL,
                    symbol      TEXT    NOT NULL,
                    action      TEXT    NOT NULL,   -- BUY / SELL_TP1 / SELL_TP2 / SELL_STOP / SELL_TRAIL / TIME_STOP / PANIC
                    price       REAL    NOT NULL,
                    qty         REAL    NOT NULL,
                    pnl         REAL,
                    r_multiple  REAL,
                    fees        REAL,
                    signal_type TEXT,               -- TREND / RANGE / BREAKOUT
                    ml_prob     REAL,
                    fused_prob  REAL,
                    mode        TEXT    DEFAULT 'PAPER'
                )
            """)

            # ---- Daily performance ----
            c.execute("""
                CREATE TABLE IF NOT EXISTS performance (
                    date        TEXT PRIMARY KEY,
                    trades      INTEGER,
                    wins        INTEGER,
                    losses      INTEGER,
                    pnl_usdt    REAL,
                    win_rate    REAL,
                    expectancy  REAL,
                    max_dd_pct  REAL
                )
            """)

            # ---- Equity curve ----
            c.execute("""
                CREATE TABLE IF NOT EXISTS equity_curve (
                    ts      TEXT PRIMARY KEY,
                    equity  REAL NOT NULL
                )
            """)

            # ---- Signal log ----
            c.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts          TEXT    NOT NULL,
                    symbol      TEXT    NOT NULL,
                    signal_type TEXT,
                    ml_prob     REAL,
                    ob_imb      REAL,
                    fused_prob  REAL,
                    action      TEXT    -- TRADE / SKIP_PROB / SKIP_HEAT / SKIP_HALTED
                )
            """)

            # ---- Indexes ----
            c.execute("CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")

    # ------------------------------------------------------------------
    # Write methods
    # ------------------------------------------------------------------

    def log_trade(
        self,
        action: str,
        symbol: str,
        price: float,
        qty: float,
        pnl: Optional[float] = None,
        r_multiple: Optional[float] = None,
        fees: float = 0.0,
        signal_type: Optional[str] = None,
        ml_prob: Optional[float] = None,
        fused_prob: Optional[float] = None,
        mode: str = "PAPER",
    ) -> None:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._cursor() as c:
            c.execute(
                """
                INSERT INTO trades
                (ts, symbol, action, price, qty, pnl, r_multiple, fees,
                 signal_type, ml_prob, fused_prob, mode)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
                (
                    ts,
                    symbol,
                    action,
                    price,
                    qty,
                    pnl,
                    r_multiple,
                    fees,
                    signal_type,
                    ml_prob,
                    fused_prob,
                    mode,
                ),
            )

    def log_equity(self, equity: float) -> None:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._cursor() as c:
            c.execute(
                "INSERT OR REPLACE INTO equity_curve (ts, equity) VALUES (?,?)",
                (ts, equity),
            )

    def update_performance(
        self,
        date: str,
        trades: int,
        wins: int,
        losses: int,
        pnl: float,
        win_rate: float,
        expectancy: float,
        max_dd: float = 0.0,
    ) -> None:
        with self._cursor() as c:
            c.execute(
                """
                INSERT OR REPLACE INTO performance
                (date, trades, wins, losses, pnl_usdt, win_rate, expectancy, max_dd_pct)
                VALUES (?,?,?,?,?,?,?,?)
            """,
                (date, trades, wins, losses, pnl, win_rate, expectancy, max_dd),
            )

    def log_signal(
        self,
        symbol: str,
        signal_type: Optional[str],
        ml_prob: float,
        ob_imb: float,
        fused_prob: float,
        action: str,
    ) -> None:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._cursor() as c:
            c.execute(
                """
                INSERT INTO signals (ts, symbol, signal_type, ml_prob, ob_imb, fused_prob, action)
                VALUES (?,?,?,?,?,?,?)
            """,
                (ts, symbol, signal_type, ml_prob, ob_imb, fused_prob, action),
            )

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    def get_equity_curve(self, days: int = 30) -> List[dict]:
        cutoff = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() - days * 86400),
        )
        with self._cursor() as c:
            c.execute(
                "SELECT ts, equity FROM equity_curve WHERE ts > ? ORDER BY ts",
                (cutoff,),
            )
            return [{"ts": r[0], "equity": r[1]} for r in c.fetchall()]

    def get_recent_trades(self, limit: int = 50) -> List[dict]:
        with self._cursor() as c:
            c.execute(
                """
                SELECT ts, symbol, action, price, qty, pnl, r_multiple, mode
                FROM trades ORDER BY id DESC LIMIT ?
            """,
                (limit,),
            )
            cols = ["ts", "symbol", "action", "price", "qty", "pnl", "r_multiple", "mode"]
            return [dict(zip(cols, r, strict=False)) for r in c.fetchall()]

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    def backup(self, backup_dir: Path) -> None:
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        dest = backup_dir / f"aegis_{ts}.db"
        try:
            dest_conn = sqlite3.connect(str(dest))
            try:
                with dest_conn:
                    self._conn.backup(dest_conn)
            finally:
                dest_conn.close()
            log.info(f"Database backed up to {dest}")
            # Prune backups older than 7 days
            cutoff = time.time() - 7 * 86400
            for f in backup_dir.glob("aegis_*.db"):
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    log.info(f"Pruned old backup: {f.name}")
        except Exception as exc:
            log.error(f"Backup failed: {exc}")


# ---------------------------------------------------------------------------
# Tick database (lightweight - inserts raw ticks for replay)
# ---------------------------------------------------------------------------


class TickDB:
    """
    Stores raw WebSocket trade ticks for each symbol.
    Table per symbol (created on demand).
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._path = db_path or PATHS["tick_db"]
        self._lock = threading.RLock()
        self._conn = _connect(self._path)
        self._tables: set = set()

    def _ensure_table(self, symbol: str) -> str:
        tbl = "ticks_" + symbol.replace("/", "_").replace("-", "_")
        if tbl not in self._tables:
            with self._lock:
                self._conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {tbl} (
                        ts      INTEGER NOT NULL,
                        price   REAL    NOT NULL,
                        qty     REAL    NOT NULL,
                        side    TEXT
                    )
                """)
                self._conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{tbl}_ts ON {tbl}(ts)")
                self._conn.commit()
                self._tables.add(tbl)
        return tbl

    def insert_tick(
        self, symbol: str, ts_ms: int, price: float, qty: float, side: str = ""
    ) -> None:
        tbl = self._ensure_table(symbol)
        with self._lock:
            self._conn.execute(
                f"INSERT INTO {tbl} (ts, price, qty, side) VALUES (?,?,?,?)",
                (ts_ms, price, qty, side),
            )
            self._conn.commit()

    def get_ticks(self, symbol: str, since_ms: int, limit: int = 10000) -> List[dict]:
        tbl = self._ensure_table(symbol)
        with self._lock:
            cur = self._conn.execute(
                f"SELECT ts, price, qty, side FROM {tbl} WHERE ts > ? ORDER BY ts LIMIT ?",
                (since_ms, limit),
            )
            return [{"ts": r[0], "price": r[1], "qty": r[2], "side": r[3]} for r in cur.fetchall()]
