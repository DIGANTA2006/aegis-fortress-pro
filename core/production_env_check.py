import os
import sys
from typing import List

REQUIRED_ENV = ["BINANCE_API_KEY", "BINANCE_SECRET"]


def check_production_env(required: List[str] = None) -> None:
    """Call explicitly from main.py - does NOT run at import time."""
    vars_to_check = required if required is not None else REQUIRED_ENV
    missing = [v for v in vars_to_check if not os.getenv(v)]
    if missing:
        print(f"[AEGIS] Missing ENV variables: {missing}", file=sys.stderr)
        sys.exit(1)
    print("[AEGIS] Environment validation passed")