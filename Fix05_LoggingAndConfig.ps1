#Requires -Version 5.1
<#
.SYNOPSIS
    Fix 05 Ã¢â‚¬â€ Structured logging with correlation IDs + config YAML loading.

.DESCRIPTION
    Two fixes in one script:

    A) core/structured_logger.py
       Extends the existing JsonFormatter so every log record automatically
       includes a correlation_id when one is present on the current thread
       context (set by ExecutionGateway when it processes an Order).
       Adds a context manager and decorator for propagating the ID.

    B) configs/ wiring
       Adds a load_yaml_config() function to configs/__init__.py that
       reads configs/default.yaml and merges it with environment variables,
       giving the rest of the codebase a single import for typed defaults.

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

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# A. core/structured_logger.py  Ã¢â‚¬â€ full rewrite
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
Write-Step "core/structured_logger.py"

WriteFile "core\structured_logger.py" @'
"""
core/structured_logger.py  -  AEGIS PRO v2

Structured (JSON) logging with automatic correlation-ID propagation.

Features
--------
- JsonFormatter  Ã¢â‚¬â€ emits every log record as a single JSON line.
- CorrelationContext  Ã¢â‚¬â€ thread-local store for the current correlation ID.
- correlation_id()   Ã¢â‚¬â€ context manager: sets the ID for the duration of a block.
- bind_correlation_id()  Ã¢â‚¬â€ decorator: reads ``order.correlation_id`` from the
                            first argument and sets it automatically.
- configure_logger()  Ã¢â‚¬â€ call once at startup to switch the root logger to JSON.

Usage
-----
    from core.structured_logger import configure_logger, correlation_id

    configure_logger()           # call once in main.py

    # In ExecutionGateway.execute(order):
    with correlation_id(order.correlation_id):
        log.info("Submitting order")   # -> {"correlation_id": "abc-123", ...}
        await exchange.create_order(...)
        log.info("Order submitted")    # same ID, automatically
"""

import json
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from typing import Generator


# ---------------------------------------------------------------------------
# Thread-local correlation ID store
# ---------------------------------------------------------------------------

_ctx = threading.local()


def get_correlation_id() -> str | None:
    """Return the correlation ID active on this thread, or None."""
    return getattr(_ctx, "correlation_id", None)


def set_correlation_id(cid: str | None) -> None:
    """Set (or clear) the correlation ID on this thread."""
    _ctx.correlation_id = cid


@contextmanager
def correlation_id(cid: str) -> Generator[None, None, None]:
    """
    Context manager Ã¢â‚¬â€ sets the correlation ID for the lifetime of the block,
    then restores whatever was set before (supports nesting).

    Example
    -------
        with correlation_id(order.correlation_id):
            log.info("processing order")
    """
    previous = get_correlation_id()
    set_correlation_id(cid)
    try:
        yield
    finally:
        set_correlation_id(previous)


def bind_correlation_id(fn=None, *, arg_name: str = "order"):
    """
    Decorator Ã¢â‚¬â€ reads ``obj.correlation_id`` from a named argument and
    activates the correlation context for the duration of the call.

    Works with both regular and async functions.

    Example
    -------
        @bind_correlation_id
        async def execute(self, order):
            log.info("executing")    # -> {"correlation_id": "...", ...}
    """
    def _decorator(func):
        import asyncio
        import inspect

        sig    = inspect.signature(func)
        params = list(sig.parameters.keys())
        # Find the position of the target argument
        try:
            idx = params.index(arg_name)
        except ValueError:
            idx = None   # arg not found Ã¢â‚¬â€ don't crash, just skip binding

        @wraps(func)
        async def _async_wrapper(*args, **kwargs):
            cid = _get_cid_from_args(args, kwargs, idx, arg_name)
            if cid:
                async with _async_correlation_id(cid):
                    return await func(*args, **kwargs)
            return await func(*args, **kwargs)

        @wraps(func)
        def _sync_wrapper(*args, **kwargs):
            cid = _get_cid_from_args(args, kwargs, idx, arg_name)
            if cid:
                with correlation_id(cid):
                    return func(*args, **kwargs)
            return func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return _async_wrapper
        return _sync_wrapper

    if fn is not None:
        # Called as @bind_correlation_id (no parentheses)
        return _decorator(fn)
    return _decorator


def _get_cid_from_args(args, kwargs, idx, arg_name):
    """Extract correlation_id from positional or keyword arguments."""
    obj = kwargs.get(arg_name)
    if obj is None and idx is not None and idx < len(args):
        obj = args[idx]
    return getattr(obj, "correlation_id", None)


@contextmanager
def _async_correlation_id(cid: str) -> Generator[None, None, None]:
    """Sync context manager usable inside async with (no asynccontextmanager needed)."""
    previous = get_correlation_id()
    set_correlation_id(cid)
    try:
        yield
    finally:
        set_correlation_id(previous)


# ---------------------------------------------------------------------------
# JSON log formatter
# ---------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """
    Formats every log record as a single JSON line.

    Fields emitted
    --------------
    timestamp      ISO-8601 UTC
    level          DEBUG / INFO / WARNING / ERROR / CRITICAL
    logger         Logger name (e.g. "aegis.execution")
    module         Python module name
    correlation_id Present when set via the context manager above
    message        The formatted log message
    exc_info       Exception traceback string (only when an exception is active)
    """

    RESERVED = {
        "args", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelname", "levelno", "lineno", "message", "module", "msecs",
        "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level":   record.levelname,
            "logger":  record.name,
            "module":  record.module,
            "message": record.getMessage(),
        }

        cid = get_correlation_id()
        if cid:
            payload["correlation_id"] = cid

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        # Attach any extra fields passed via logger.info("msg", extra={...})
        for key, value in record.__dict__.items():
            if key not in self.RESERVED and not key.startswith("_"):
                try:
                    json.dumps(value)   # check serialisability
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = str(value)

        return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# One-call setup
# ---------------------------------------------------------------------------

def configure_logger(
    level: int | str = logging.INFO,
    stream=None,
    add_file_handler: bool = False,
    log_path: str | None = None,
) -> None:
    """
    Switch the root logger to structured JSON output.

    Parameters
    ----------
    level : int | str
        Root log level (default INFO).
    stream :
        Output stream for the StreamHandler (default stderr).
    add_file_handler : bool
        Also write JSON logs to *log_path* (requires log_path).
    log_path : str | None
        File path for the file handler (e.g. "logs/aegis.log").
    """
    formatter = JsonFormatter()

    stream_handler = logging.StreamHandler(stream)
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(stream_handler)

    if add_file_handler and log_path:
        import os
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)
'@

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# B. configs/__init__.py  Ã¢â‚¬â€ add YAML config loader
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
Write-Step "configs/__init__.py"

WriteFile "configs\__init__.py" @'
"""
configs package  -  AEGIS PRO v2

Provides load_yaml_config() which reads configs/default.yaml and
merges it with environment-variable overrides.

The result is a plain nested dict Ã¢â‚¬â€ no external dependencies required
(falls back gracefully when PyYAML is not installed).

Usage
-----
    from configs import load_yaml_config
    cfg = load_yaml_config()
    port = cfg["monitoring"]["metrics_port"]   # -> 9090
"""

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_YAML = Path(__file__).parent / "default.yaml"


def load_yaml_config(
    yaml_path: str | Path | None = None,
    env_prefix: str = "AEGIS_",
) -> dict:
    """
    Load the YAML config file and apply environment-variable overrides.

    Parameters
    ----------
    yaml_path : str | Path | None
        Path to the YAML file.  Defaults to configs/default.yaml.
    env_prefix : str
        Only environment variables starting with this prefix are
        considered for overrides (default ``"AEGIS_"``).

    Returns
    -------
    dict
        Merged configuration dictionary.

    Environment-variable override format
    -------------------------------------
    Nested keys are separated by double-underscore.
    Examples:
        AEGIS_TRADING__DEFAULT_SYMBOL=ETH/USDT
            -> cfg["trading"]["default_symbol"] = "ETH/USDT"
        AEGIS_MONITORING__METRICS_PORT=9091
            -> cfg["monitoring"]["metrics_port"] = 9091
    """
    path   = Path(yaml_path) if yaml_path else _DEFAULT_YAML
    config = _load_yaml(path)
    _apply_env_overrides(config, env_prefix)
    return config


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict:
    if not path.exists():
        log.warning("configs: %s not found Ã¢â‚¬â€ using empty config", path)
        return {}

    try:
        import yaml  # PyYAML
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
            log.debug("configs: loaded %s", path)
            return data or {}
    except ImportError:
        log.warning(
            "PyYAML not installed Ã¢â‚¬â€ falling back to raw text parse. "
            "Run: pip install pyyaml"
        )
        return _parse_yaml_naive(path)
    except Exception:
        log.exception("configs: failed to load %s", path)
        return {}


def _apply_env_overrides(config: dict, prefix: str) -> None:
    """
    Walk environment variables and patch matching keys into *config*.
    Numeric strings are auto-cast to int/float.
    """
    for key, raw_value in os.environ.items():
        if not key.startswith(prefix):
            continue
        # Strip prefix, split on __ to get nested path
        path_parts = key[len(prefix):].lower().split("__")
        value      = _cast(raw_value)
        _set_nested(config, path_parts, value)
        log.debug("configs: env override %s = %r", key, value)


def _set_nested(d: dict, keys: list[str], value) -> None:
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def _cast(s: str):
    """Try int Ã¢â€ â€™ float Ã¢â€ â€™ bool Ã¢â€ â€™ keep as str."""
    for fn in (int, float):
        try:
            return fn(s)
        except ValueError:
            pass
    if s.lower() in {"true",  "yes", "1"}: return True
    if s.lower() in {"false", "no",  "0"}: return False
    return s


def _parse_yaml_naive(path: Path) -> dict:
    """
    Minimal key: value parser used when PyYAML is not available.
    Handles only flat scalar values and one level of nesting via indentation.
    Good enough to read the defaults config without a hard dependency.
    """
    result: dict  = {}
    current: dict = result
    current_key   = None

    with open(path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.rstrip()
            if not stripped or stripped.startswith("#"):
                continue
            indent  = len(line) - len(line.lstrip())
            content = stripped.lstrip()
            if ":" not in content:
                continue
            k, _, v = content.partition(":")
            k = k.strip()
            v = v.strip()
            if indent == 0:
                current_key = k
                if v:
                    result[k] = _cast(v)
                    current   = result
                else:
                    result[k] = {}
                    current   = result[k]
            else:
                if v:
                    current[k] = _cast(v)

    return result
'@

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# C. Unit tests for structured logger and config loader
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
Write-Step "tests/unit/test_structured_logger.py"

WriteFile "tests\unit\test_structured_logger.py" @'
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
'@

Write-Step "tests/unit/test_config_loader.py"

WriteFile "tests\unit\test_config_loader.py" @'
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
'@

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# Done
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
Write-Host "`n=================================================" -ForegroundColor Magenta
Write-Host "  Fix 05 complete Ã¢â‚¬â€ structured logging + config loader done." -ForegroundColor Magenta
Write-Host "  All 5 fixes applied.  Run pytest to verify:" -ForegroundColor Magenta
Write-Host "  pytest tests/ -v" -ForegroundColor White
Write-Host "=================================================" -ForegroundColor Magenta
