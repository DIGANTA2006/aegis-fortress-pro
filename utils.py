"""
utils.py  -  AEGIS PRO v2
Shared utilities: atomic file I/O, structured logging, retry decorator,
token-bucket rate limiter, and misc helpers.
"""

import json
import logging
import math
import os
import random
import sys
import threading
import time
import traceback
from datetime import datetime
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Structured / rotating logger
# ---------------------------------------------------------------------------

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def setup_logger(
    name: str = "aegis",
    log_path: Optional[Path] = None,
    level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
) -> logging.Logger:
    """
    Create a logger that writes to stdout AND a rotating file.
    Safe to call multiple times - returns the same logger if already configured.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(level)
    fmt = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Console handler
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    # File handler
    if log_path:
        fh = RotatingFileHandler(
            log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


log = setup_logger("aegis.utils")


# ---------------------------------------------------------------------------
# Atomic file write (cross-platform)
# ---------------------------------------------------------------------------


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON data atomically using rename-swap."""
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
        if os.name != "nt":
            with tmp.open("ab") as _fh:
                os.fsync(_fh.fileno())
        tmp.replace(path)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write binary data atomically."""
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def safe_read_json(path: Path, default: Any = None) -> Any:
    """Read JSON, returning default on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Retry decorator with exponential back-off + jitter
# ---------------------------------------------------------------------------


def retry(
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: tuple = (Exception,),
    logger: Optional[logging.Logger] = None,
):
    """
    Decorator: retry on specified exceptions with exponential back-off + jitter.

    Usage:
        @retry(max_attempts=4, exceptions=(ccxt.NetworkError,))
        def fetch_data():
            ...
    """
    _log = logger or log

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc: Optional[Exception] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        break
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    jitter = random.uniform(0.75, 1.25)
                    sleep_time = delay * jitter
                    _log.warning(
                        f"{fn.__name__}: attempt {attempt}/{max_attempts} failed "
                        f"({exc}). Retrying in {sleep_time:.1f}s."
                    )
                    time.sleep(sleep_time)
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Token-bucket rate limiter
# ---------------------------------------------------------------------------


class TokenBucket:
    """
    Thread-safe token-bucket rate limiter.

    Example:
        bucket = TokenBucket(rate=10, capacity=20)  # 10 calls/second, burst=20
        bucket.consume()   # blocks until a token is available
    """

    def __init__(self, rate: float, capacity: float):
        self.rate = rate  # tokens per second
        self.capacity = capacity
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    def consume(self, tokens: float = 1.0, block: bool = True) -> bool:
        """
        Consume tokens.  If block=True, sleeps until tokens are available.
        Returns True if consumed, False if not available (only when block=False).
        """
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
            if not block:
                return False
            # Sleep for a short interval then retry
            time.sleep(tokens / self.rate * 0.1 + 0.001)


# ---------------------------------------------------------------------------
# Decimal-safe JSON encoder
# ---------------------------------------------------------------------------


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        try:
            from decimal import Decimal

            if isinstance(obj, Decimal):
                return float(obj)
        except ImportError:
            pass
        return super().default(obj)


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def pct_change(new: float, old: float) -> float:
    if old == 0:
        return 0.0
    return (new - old) / abs(old)


def format_usdt(val: float) -> str:
    return f"${val:,.2f}"


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    return a / b if b != 0 else default


def chunks(lst: list, n: int):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def format_telegram_trade(
    action: str,
    symbol: str,
    price: float,
    qty: float,
    pnl: Optional[float] = None,
    mode: str = "PAPER",
) -> str:
    """Build an HTML-formatted Telegram message for a trade event."""
    mode_tag = "Ã°Å¸Å¸Â¡ PAPER" if mode == "PAPER" else "Ã°Å¸Å¸Â¢ LIVE"
    lines = [
        f"<b>{action}</b>  {symbol}  [{mode_tag}]",
        f"Price: <code>{price:.6g}</code>",
        f"Qty: <code>{qty:.6g}</code>",
    ]
    if pnl is not None:
        sign = "+" if pnl >= 0 else ""
        lines.append(f"PnL: <b>{sign}{pnl:.2f} USDT</b>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Crash-safe execution wrapper
# ---------------------------------------------------------------------------


def safe_call(
    fn: Callable, *args, logger: Optional[logging.Logger] = None, default: Any = None, **kwargs
) -> Any:
    """Call fn(*args, **kwargs), log exceptions, return default on error."""
    _log = logger or log
    try:
        return fn(*args, **kwargs)
    except Exception:
        _log.error(f"safe_call({fn.__name__}) failed:\n{traceback.format_exc()}")
        return default
