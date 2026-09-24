import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class DatabaseManager:
    def __init__(
        self,
        db_path: str = "data/aegis_runtime.db",
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()

        self._initialize_schema()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10,
            check_same_thread=False,
        )

        conn.row_factory = sqlite3.Row

        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")

        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _initialize_schema(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id TEXT,
            order_id TEXT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            exchange TEXT NOT NULL,
            pnl REAL NOT NULL,
            fee REAL NOT NULL,
            strategy_id TEXT,
            timestamp TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS execution_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            correlation_id TEXT,
            exchange_order_id TEXT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            requested_quantity REAL NOT NULL,
            filled_quantity REAL NOT NULL,
            average_fill_price REAL NOT NULL,
            status TEXT NOT NULL,
            exchange TEXT NOT NULL,
            fee REAL NOT NULL,
            timestamp TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS risk_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            correlation_id TEXT,
            severity TEXT NOT NULL,
            code TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS health_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            healthy INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_trades_symbol
            ON trades(symbol);

        CREATE INDEX IF NOT EXISTS idx_trades_timestamp
            ON trades(timestamp);

        CREATE INDEX IF NOT EXISTS idx_execution_reports_symbol
            ON execution_reports(symbol);

        CREATE INDEX IF NOT EXISTS idx_execution_reports_timestamp
            ON execution_reports(timestamp);

        CREATE INDEX IF NOT EXISTS idx_risk_events_timestamp
            ON risk_events(timestamp);
        """

        with self._lock:
            with self._connection() as conn:
                conn.executescript(schema)

    def ping(self) -> bool:
        try:
            with self._lock:
                with self._connection() as conn:
                    conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def record_trade(self, trade: Any) -> None:
        payload = self._to_dict(trade)

        with self._lock:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO trades (
                        trade_id,
                        order_id,
                        symbol,
                        side,
                        quantity,
                        price,
                        exchange,
                        pnl,
                        fee,
                        strategy_id,
                        timestamp,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload.get("trade_id"),
                        payload.get("order_id"),
                        payload.get("symbol"),
                        payload.get("side"),
                        payload.get("quantity", 0.0),
                        payload.get("price", 0.0),
                        payload.get("exchange"),
                        payload.get("pnl", 0.0),
                        payload.get("fee", 0.0),
                        payload.get("strategy_id"),
                        payload.get("timestamp"),
                        self._json(payload),
                    ),
                )

    def record_execution_report(self, report: Any) -> None:
        payload = self._to_dict(report)

        with self._lock:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO execution_reports (
                        correlation_id,
                        exchange_order_id,
                        symbol,
                        side,
                        requested_quantity,
                        filled_quantity,
                        average_fill_price,
                        status,
                        exchange,
                        fee,
                        timestamp,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload.get("correlation_id"),
                        payload.get("exchange_order_id"),
                        payload.get("symbol"),
                        payload.get("side"),
                        payload.get("requested_quantity", 0.0),
                        payload.get("filled_quantity", 0.0),
                        payload.get("average_fill_price", 0.0),
                        payload.get("status"),
                        payload.get("exchange"),
                        payload.get("fee", 0.0),
                        payload.get("timestamp"),
                        self._json(payload),
                    ),
                )

    def record_risk_event(self, event_payload: dict) -> None:
        payload = dict(event_payload)

        with self._lock:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO risk_events (
                        correlation_id,
                        severity,
                        code,
                        message,
                        timestamp,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload.get("correlation_id"),
                        payload.get("severity", "UNKNOWN"),
                        payload.get("code", "UNKNOWN"),
                        payload.get("message", ""),
                        payload.get("timestamp"),
                        self._json(payload),
                    ),
                )

    def record_health_snapshot(self, payload: dict) -> None:
        healthy = bool(payload.get("healthy", False))
        captured_at = payload.get("captured_at")

        with self._lock:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO health_snapshots (
                        captured_at,
                        healthy,
                        payload_json
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        captured_at,
                        int(healthy),
                        self._json(payload),
                    ),
                )

    def fetch_recent_trades(self, limit: int = 100) -> list[dict]:
        return self._fetch_recent(
            table="trades",
            limit=limit,
        )

    def fetch_recent_execution_reports(self, limit: int = 100) -> list[dict]:
        return self._fetch_recent(
            table="execution_reports",
            limit=limit,
        )

    def fetch_recent_risk_events(self, limit: int = 100) -> list[dict]:
        return self._fetch_recent(
            table="risk_events",
            limit=limit,
        )

    def _fetch_recent(
        self,
        table: str,
        limit: int,
    ) -> list[dict]:
        allowed = {
            "trades",
            "execution_reports",
            "risk_events",
        }

        if table not in allowed:
            raise ValueError("Unsupported table requested")

        if limit <= 0:
            raise ValueError("limit must be positive")

        with self._lock:
            with self._connection() as conn:
                rows = conn.execute(
                    f"""
                    SELECT payload_json
                    FROM {table}
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

        return [
            json.loads(row["payload_json"])
            for row in rows
        ]

    def _to_dict(self, value: Any) -> dict:
        if isinstance(value, dict):
            return value

        to_dict = getattr(value, "to_dict", None)

        if callable(to_dict):
            return to_dict()

        raise TypeError("Object must be a dictionary or expose to_dict()")

    def _json(self, payload: dict) -> str:
        return json.dumps(
            payload,
            sort_keys=True,
            default=str,
        )
