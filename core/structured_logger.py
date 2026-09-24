import json
import logging
import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Iterator


correlation_id_ctx: ContextVar[str | None] = ContextVar(
    "correlation_id",
    default=None,
)

service_name_ctx: ContextVar[str | None] = ContextVar(
    "service_name",
    default=None,
)


def set_correlation_id(value: str | None) -> None:
    correlation_id_ctx.set(value)


def get_correlation_id() -> str | None:
    return correlation_id_ctx.get()


def set_service_name(value: str | None) -> None:
    service_name_ctx.set(value)


def get_service_name() -> str | None:
    return service_name_ctx.get()


@contextmanager
def correlation_id(value: str | None) -> Iterator[None]:
    token = correlation_id_ctx.set(value)

    try:
        yield
    finally:
        correlation_id_ctx.reset(token)


@contextmanager
def service_name(value: str | None) -> Iterator[None]:
    token = service_name_ctx.set(value)

    try:
        yield
    finally:
        service_name_ctx.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }

        current_correlation_id = get_correlation_id()
        current_service_name = get_service_name()

        if current_correlation_id is not None:
            payload["correlation_id"] = current_correlation_id

        if current_service_name is not None:
            payload["service"] = current_service_name

        if record.exc_info:
            payload["exc_info"] = self.formatException(
                record.exc_info
            )

        return json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
        )


def configure_logger(
    log_dir: str = "logs",
    log_file: str = "aegis_runtime.jsonl",
    level: str | int | None = None,
) -> None:
    if isinstance(level, int):
        numeric_level = level

    else:
        configured_level = (
            str(level)
            if level is not None
            else os.environ.get("AEGIS_LOG_LEVEL", "INFO")
        ).upper()

        numeric_level = getattr(
            logging,
            configured_level,
            logging.INFO,
        )

    root = logging.getLogger()
    root.setLevel(numeric_level)
    root.handlers.clear()

    formatter = JsonFormatter()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    Path(log_dir).mkdir(
        parents=True,
        exist_ok=True,
    )

    file_handler = logging.FileHandler(
        Path(log_dir) / log_file,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root.addHandler(stream_handler)
    root.addHandler(file_handler)