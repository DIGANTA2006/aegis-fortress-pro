from __future__ import annotations

import argparse
import json
import os
import py_compile
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
SKIP_DIRS = {
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "unused_scripts_backup",
    "logs",
}


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_env_file(env_file: str = ".env") -> None:
    path = resolve_path(env_file)

    if not path.exists():
        print(f"Environment file not found: {path}. Continuing with current environment.")
        return

    for raw_line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()

        if (
            len(value) >= 2
            and (
                (value.startswith('"') and value.endswith('"'))
                or (value.startswith("'") and value.endswith("'"))
            )
        ):
            value = value[1:-1]

        os.environ[name] = value


def select_exchange_profiles() -> None:
    mode = os.environ.get("AEGIS_MODE", "PAPER").strip().upper() or "PAPER"

    if mode not in {"PAPER", "LIVE"}:
        raise SystemExit(f"Invalid AEGIS_MODE={mode!r}. Use PAPER or LIVE.")

    os.environ["AEGIS_MODE"] = mode

    if mode == "LIVE":
        confirm = os.environ.get("AEGIS_LIVE_CONFIRM", "").strip()

        if confirm != "YES_I_ACCEPT_THE_RISK":
            raise SystemExit(
                "LIVE mode blocked. Set AEGIS_LIVE_CONFIRM=YES_I_ACCEPT_THE_RISK "
                "only when you truly accept the risk."
            )

    def select_profile(
        exchange_name: str,
        testnet_key: str,
        testnet_secret: str,
        live_key: str,
        live_secret: str,
        runtime_key: str,
        runtime_secret: str,
        required_in_live: bool = False,
    ) -> None:
        if mode == "PAPER":
            key = os.environ.get(testnet_key, "").strip()
            secret = os.environ.get(testnet_secret, "").strip()
            profile = "PAPER/Testnet"
        else:
            key = os.environ.get(live_key, "").strip()
            secret = os.environ.get(live_secret, "").strip()
            profile = "LIVE"

        if mode == "LIVE" and required_in_live and (not key or not secret):
            raise SystemExit(
                f"{exchange_name} LIVE credentials missing. "
                f"Fill {live_key} and {live_secret}."
            )

        os.environ[runtime_key] = key
        os.environ[runtime_secret] = secret

        status = "selected" if key and secret else "not set / market-data only"
        print(f"{exchange_name} {profile} credentials: {status}")

    select_profile(
        "Binance",
        "BINANCE_TESTNET_API_KEY",
        "BINANCE_TESTNET_SECRET",
        "BINANCE_LIVE_API_KEY",
        "BINANCE_LIVE_SECRET",
        "BINANCE_API_KEY",
        "BINANCE_SECRET",
        required_in_live=True,
    )

    select_profile(
        "Bybit",
        "BYBIT_TESTNET_API_KEY",
        "BYBIT_TESTNET_SECRET",
        "BYBIT_LIVE_API_KEY",
        "BYBIT_LIVE_SECRET",
        "BYBIT_API_KEY",
        "BYBIT_SECRET",
        required_in_live=False,
    )

    select_profile(
        "OKX",
        "OKX_TESTNET_API_KEY",
        "OKX_TESTNET_SECRET",
        "OKX_LIVE_API_KEY",
        "OKX_LIVE_SECRET",
        "OKX_API_KEY",
        "OKX_SECRET",
        required_in_live=False,
    )

    if mode == "PAPER":
        okx_passphrase = (
            os.environ.get("OKX_TESTNET_PASSPHRASE", "").strip()
            or os.environ.get("OKX_TESTNET_PASSWORD", "").strip()
        )
    else:
        okx_passphrase = (
            os.environ.get("OKX_LIVE_PASSPHRASE", "").strip()
            or os.environ.get("OKX_LIVE_PASSWORD", "").strip()
        )

    os.environ["OKX_PASSPHRASE"] = okx_passphrase
    os.environ["OKX_PASSWORD"] = okx_passphrase

    okx_status = "selected" if (
        os.environ.get("OKX_API_KEY")
        and os.environ.get("OKX_SECRET")
        and os.environ.get("OKX_PASSPHRASE")
    ) else "not set / market-data only"

    print(f"OKX {mode} credentials: {okx_status}")

    print(f"AEGIS mode: {mode}")


def bootstrap_environment(env_file: str = ".env") -> None:
    load_env_file(env_file)
    select_exchange_profiles()


def run_command(command: Iterable[str], check: bool = True) -> int:
    cmd = [str(item) for item in command]
    print("")
    print(">>>", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)

    if check and result.returncode != 0:
        raise SystemExit(result.returncode)

    return result.returncode


def iter_project_python_files():
    for file in ROOT.rglob("*.py"):
        parts = set(file.relative_to(ROOT).parts)
        if parts & SKIP_DIRS:
            continue
        yield file


def command_compile(args: argparse.Namespace) -> None:
    count = 0

    for file in iter_project_python_files():
        py_compile.compile(str(file), doraise=True)
        count += 1

    print(f"Compiled {count} project Python files.")


def command_run(args: argparse.Namespace) -> None:
    bootstrap_environment(args.env_file)

    from app.runtime_runner import main as runtime_main

    runtime_main()


def command_preflight(args: argparse.Namespace) -> None:
    bootstrap_environment(args.env_file)
    run_command([sys.executable, "scripts/preflight_check.py"])


def command_test(args: argparse.Namespace) -> None:
    bootstrap_environment(args.env_file)
    run_command([sys.executable, "-m", "pytest"])


def command_readiness(args: argparse.Namespace) -> None:
    bootstrap_environment(args.env_file)

    command_compile(args)
    run_command([sys.executable, "-m", "pytest"])
    run_command([sys.executable, "scripts/preflight_check.py"])

    freeze_script = ROOT / "scripts" / "freeze_requirements.ps1"

    if freeze_script.exists() and os.name == "nt":
        run_command(
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(freeze_script),
            ],
            check=False,
        )

    print("")
    print("AEGIS readiness checks passed.")


def command_clean(args: argparse.Namespace) -> None:
    script = ROOT / "scripts" / "clean_runtime_artifacts.ps1"

    if os.name == "nt" and script.exists():
        run_command(
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ]
        )
        return

    import shutil

    for pattern in ["**/__pycache__", ".pytest_cache", ".ruff_cache"]:
        for item in ROOT.glob(pattern):
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)

    print("Runtime/cache cleanup completed.")


def command_freeze(args: argparse.Namespace) -> None:
    script = ROOT / "scripts" / "freeze_requirements.ps1"

    if os.name == "nt" and script.exists():
        run_command(
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ]
        )
        return

    output = subprocess.check_output(
        [sys.executable, "-m", "pip", "freeze"],
        cwd=ROOT,
        text=True,
    )

    (ROOT / "requirements.lock.txt").write_text(
        "\n".join(sorted(output.splitlines())) + "\n",
        encoding="utf-8",
    )

    print("Created requirements.lock.txt")


def get_json(url: str) -> object:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def command_verify(args: argparse.Namespace) -> None:
    health_url = f"http://{args.host}:{args.health_port}/health"
    ready_url = f"http://{args.host}:{args.health_port}/ready"
    metrics_url = f"http://{args.host}:{args.metrics_port}/metrics"

    print("")
    print("Checking health endpoint:")
    print(health_url)
    print(json.dumps(get_json(health_url), indent=2))

    print("")
    print("Checking readiness endpoint:")
    print(ready_url)
    print(json.dumps(get_json(ready_url), indent=2))

    print("")
    print("Checking Prometheus metrics endpoint:")
    print(metrics_url)

    with urllib.request.urlopen(metrics_url, timeout=10) as response:
        metrics = response.read().decode("utf-8", errors="replace")

    if "aegis_" not in metrics:
        raise SystemExit("Metrics endpoint responded, but AEGIS metrics were not found.")

    print("Metrics endpoint OK.")


def command_watch(args: argparse.Namespace) -> None:
    url = f"http://{args.host}:{args.health_port}/health"

    while True:
        try:
            health = get_json(url)
            services = health["runtime"]["services"]

            strategy = services["live-strategy-service"]["metrics"]
            execution = services["execution-service"]["metrics"]

            print("\033c", end="")
            print("========== AEGIS LIVE PAPER WATCH ==========")
            print("Ticks seen              :", strategy.get("market_ticks_seen"))
            print("Orderbooks seen         :", strategy.get("orderbooks_seen"))
            print("Signals generated       :", strategy.get("strategy", {}).get("signals_generated"))
            print("Order requests published:", strategy.get("order_requests_published"))
            print("")
            print("Execution received      :", execution.get("received_requests"))
            print("Execution accepted      :", execution.get("accepted_requests"))
            print("Execution rejected      :", execution.get("rejected_requests"))
            print("Execution failed        :", execution.get("failed_requests"))
            print("============================================")
            print("Press Ctrl + C to stop watching.")

            time.sleep(args.interval)

        except KeyboardInterrupt:
            print("")
            print("Watch stopped.")
            return

        except Exception as exc:
            print("Watch error:", exc)
            time.sleep(args.interval)


def table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    return (
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def column_exists(cur: sqlite3.Cursor, table: str, column: str) -> bool:
    return any(
        row[1] == column
        for row in cur.execute(f"PRAGMA table_info({table})").fetchall()
    )


def command_profit(args: argparse.Namespace) -> None:
    db_path = resolve_path(args.db)

    if not db_path.exists():
        print(f"No runtime database found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    if not table_exists(cur, "trades"):
        print("No trades table exists yet. No executed trades have been recorded.")
        conn.close()
        return

    trade_count = cur.execute("SELECT COUNT(*) FROM trades").fetchone()[0]

    buy_count = 0
    sell_count = 0

    if column_exists(cur, "trades", "side"):
        buy_count = cur.execute(
            "SELECT COUNT(*) FROM trades WHERE UPPER(side)='BUY'"
        ).fetchone()[0]

        sell_count = cur.execute(
            "SELECT COUNT(*) FROM trades WHERE UPPER(side)='SELL'"
        ).fetchone()[0]

    realized_pnl = 0.0
    fees = 0.0

    if column_exists(cur, "trades", "pnl"):
        realized_pnl = float(
            cur.execute("SELECT COALESCE(SUM(pnl), 0) FROM trades").fetchone()[0]
        )

    if column_exists(cur, "trades", "fee"):
        fees = float(
            cur.execute("SELECT COALESCE(SUM(fee), 0) FROM trades").fetchone()[0]
        )

    print("========== AEGIS PAPER TRADE REPORT ==========")
    print(f"Database              : {db_path}")
    print(f"Trades recorded       : {trade_count}")
    print(f"Buy trades            : {buy_count}")
    print(f"Sell trades           : {sell_count}")
    print(f"Realized PnL          : {realized_pnl:.8f}")
    print(f"Fees recorded         : {fees:.8f}")
    print(f"Net realized result   : {(realized_pnl - fees):.8f}")
    print("==============================================")

    conn.close()


class NullStrategy:
    def on_market_tick(self, tick: dict):
        return None


def command_backtest_runtime(args: argparse.Namespace) -> None:
    replay_file = resolve_path(args.replay_file)

    if not replay_file.exists():
        raise SystemExit(f"Replay file not found: {replay_file}")

    from backtesting.backtest_runtime import BacktestRuntime

    runtime = BacktestRuntime(
        strategy=NullStrategy(),
        replay_file=str(replay_file),
    )

    result = runtime.run_sync()

    print(json.dumps(result.to_dict(), indent=2, default=str))


def command_legacy(args: argparse.Namespace) -> None:
    legacy = ROOT / "main_legacy.py"

    if not legacy.exists():
        raise SystemExit("main_legacy.py not found.")

    run_command([sys.executable, str(legacy)] + args.legacy_args)


def command_doctor(args: argparse.Namespace) -> None:
    checks = []

    def has(path: str, text: str) -> None:
        p = ROOT / path
        ok = p.exists() and text in p.read_text(encoding="utf-8-sig", errors="replace")
        checks.append((path, ok))

    has("main.py", "AEGIS v2 unified controller")
    has("runtime_main.py", 'main(["run"])')
    has("backtest_runtime_main.py", 'main(["backtest-runtime"]')
    has("scripts/start_runtime.ps1", "python main.py --env-file $EnvFile run")
    has("scripts/production_readiness.ps1", "python main.py --env-file $EnvFile readiness")
    has("scripts/verify_runtime_endpoints.ps1", "python main.py verify")
    has("Dockerfile", '["python", "main.py", "run"]')
    has("aegis-pro.service", "main.py run")
    has("RUN_AEGIS.ps1", "python main.py run")

    deploy_service = ROOT / "deploy" / "new" / "templates" / "aegis-pro.service.j2"
    if deploy_service.exists():
        has("deploy/new/templates/aegis-pro.service.j2", "main.py run")

    failed = [item for item in checks if not item[1]]

    print("========== AEGIS ENTRYPOINT DOCTOR ==========")
    for path, ok in checks:
        print(("PASS" if ok else "FAIL"), path)
    print("=============================================")

    if failed:
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AEGIS v2 unified controller")

    parser.add_argument(
        "--env-file",
        default=".env",
        help="Environment file to load before running commands.",
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run").set_defaults(func=command_run)
    sub.add_parser("preflight").set_defaults(func=command_preflight)
    sub.add_parser("readiness").set_defaults(func=command_readiness)
    sub.add_parser("test").set_defaults(func=command_test)
    sub.add_parser("compile").set_defaults(func=command_compile)
    sub.add_parser("clean").set_defaults(func=command_clean)
    sub.add_parser("freeze").set_defaults(func=command_freeze)
    sub.add_parser("doctor").set_defaults(func=command_doctor)

    verify = sub.add_parser("verify")
    verify.add_argument("--host", default="127.0.0.1")
    verify.add_argument("--health-port", type=int, default=8080)
    verify.add_argument("--metrics-port", type=int, default=9000)
    verify.set_defaults(func=command_verify)

    watch = sub.add_parser("watch")
    watch.add_argument("--host", default="127.0.0.1")
    watch.add_argument("--health-port", type=int, default=8080)
    watch.add_argument("--interval", type=int, default=15)
    watch.set_defaults(func=command_watch)

    profit = sub.add_parser("profit")
    profit.add_argument("--db", default="data/aegis_runtime.db")
    profit.set_defaults(func=command_profit)

    bt = sub.add_parser("backtest-runtime")
    bt.add_argument("replay_file")
    bt.set_defaults(func=command_backtest_runtime)

    legacy = sub.add_parser("legacy")
    legacy.add_argument("legacy_args", nargs=argparse.REMAINDER)
    legacy.set_defaults(func=command_legacy)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        args.command = "run"
        args.func = command_run

    args.func(args)


if __name__ == "__main__":
    main()
