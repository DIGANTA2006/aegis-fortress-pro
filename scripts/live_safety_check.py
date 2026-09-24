from __future__ import annotations

import argparse
import os
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}

    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[name.strip()] = value

    return values


def as_float(values: dict[str, str], name: str, default: float) -> float:
    raw = values.get(name) or os.environ.get(name) or ""
    if not raw:
        return default
    return float(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description="AEGIS live safety guard")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--max-live-order-usdt", type=float, default=10.0)
    parser.add_argument("--max-live-daily-loss-usdt", type=float, default=2.0)
    args = parser.parse_args()

    env_path = Path(args.env_file)
    values = load_env(env_path)

    merged = dict(os.environ)
    merged.update(values)

    mode = (merged.get("AEGIS_MODE") or "PAPER").strip().upper()
    errors: list[str] = []
    warnings: list[str] = []

    if mode != "LIVE":
        print("AEGIS safety check: PAPER/TEST mode detected. Live trading is not enabled.")
        return 0

    if merged.get("AEGIS_LIVE_CONFIRM", "").strip() != "YES_I_ACCEPT_THE_RISK":
        errors.append("AEGIS_LIVE_CONFIRM is not set to YES_I_ACCEPT_THE_RISK.")

    execution_exchanges = [
        item.strip().lower()
        for item in (merged.get("AEGIS_EXECUTION_EXCHANGES") or "").split(",")
        if item.strip()
    ]
    if not execution_exchanges:
        errors.append("AEGIS_EXECUTION_EXCHANGES is empty; set it explicitly, e.g. binance.")

    live_key_pairs = {
        "binance": ("BINANCE_LIVE_API_KEY", "BINANCE_LIVE_SECRET"),
        "bybit": ("BYBIT_LIVE_API_KEY", "BYBIT_LIVE_SECRET"),
        "okx": ("OKX_LIVE_API_KEY", "OKX_LIVE_SECRET"),
    }

    for exchange in execution_exchanges:
        key_pair = live_key_pairs.get(exchange)
        if key_pair is None:
            errors.append(f"Unsupported execution exchange for live guard: {exchange}.")
            continue
        key_name, secret_name = key_pair
        if not merged.get(key_name) or not merged.get(secret_name):
            errors.append(f"Missing live credentials for execution exchange {exchange}: {key_name}/{secret_name}.")

    try:
        max_order = as_float(merged, "AEGIS_MAX_ORDER_NOTIONAL", 0.0)
        strategy_order = as_float(merged, "AEGIS_STRATEGY_TARGET_NOTIONAL", 0.0)
        daily_loss = as_float(merged, "AEGIS_MAX_DAILY_LOSS", 0.0)
    except ValueError as exc:
        errors.append(f"Invalid numeric risk setting: {exc}")
        max_order = strategy_order = daily_loss = 0.0

    if max_order <= 0:
        errors.append("AEGIS_MAX_ORDER_NOTIONAL must be positive.")
    elif max_order > args.max_live_order_usdt:
        errors.append(
            f"AEGIS_MAX_ORDER_NOTIONAL={max_order} exceeds live guard limit {args.max_live_order_usdt} USDT."
        )

    if strategy_order <= 0:
        errors.append("AEGIS_STRATEGY_TARGET_NOTIONAL must be positive.")
    elif strategy_order > args.max_live_order_usdt:
        errors.append(
            f"AEGIS_STRATEGY_TARGET_NOTIONAL={strategy_order} exceeds live guard limit {args.max_live_order_usdt} USDT."
        )

    if daily_loss <= 0:
        errors.append("AEGIS_MAX_DAILY_LOSS must be positive.")
    elif daily_loss > args.max_live_daily_loss_usdt:
        errors.append(
            f"AEGIS_MAX_DAILY_LOSS={daily_loss} exceeds live guard limit {args.max_live_daily_loss_usdt} USDT."
        )

    order_type = (merged.get("AEGIS_STRATEGY_ORDER_TYPE") or "").strip().upper()
    if order_type not in {"MARKET", "LIMIT"}:
        errors.append("AEGIS_STRATEGY_ORDER_TYPE must be MARKET or LIMIT.")

    blocklist = (merged.get("AEGIS_SYMBOL_BLOCKLIST") or "").strip()
    if not blocklist:
        warnings.append("AEGIS_SYMBOL_BLOCKLIST is empty. Add risky event/unlock coins manually.")

    if errors:
        print("AEGIS LIVE SAFETY CHECK: BLOCKED")
        for item in errors:
            print(f"[BLOCK] {item}")
        for item in warnings:
            print(f"[WARN] {item}")
        print("Do not run live until every [BLOCK] item is fixed.")
        return 1

    print("AEGIS LIVE SAFETY CHECK: PASSED with remaining manual responsibilities.")
    for item in warnings:
        print(f"[WARN] {item}")
    print("Manual check still required: exchange API key must have withdrawal disabled and spot-only trading permission.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
