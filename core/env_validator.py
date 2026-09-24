import os
from typing import List

REQUIRED_ENV = ["BINANCE_API_KEY", "BINANCE_SECRET"]


def validate_env(required: List[str] = None) -> List[str]:
    """Return list of missing env var names (empty = all present)."""
    vars_to_check = required if required is not None else REQUIRED_ENV
    return [x for x in vars_to_check if not os.getenv(x)]


def validate_env_strict(required: List[str] = None) -> None:
    """Raise RuntimeError if any required env vars are missing."""
    missing = validate_env(required)
    if missing:
        raise RuntimeError(f"Missing ENV variables: {missing}")