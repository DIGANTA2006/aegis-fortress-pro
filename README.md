# AEGIS Fortress Pro

A modular cryptocurrency trading, backtesting, risk-management, and observability framework built around a unified Python runtime.

> **Status:** Research / paper-trading / staged-live framework. Live trading is intentionally gated and requires explicit configuration and operational checks. This project does **not** guarantee profitability or eliminate market/exchange risk.

## What is AEGIS Fortress Pro?

AEGIS Fortress Pro combines the broader AEGIS runtime with the Fortress momentum-trap scanner. Instead of putting market data, signal generation, execution, risk, persistence, and monitoring in one script, the project separates these responsibilities into testable modules.

The current codebase includes:

- **Market data and exchange connectivity** through CCXT, with Binance, Bybit, and OKX integration points.
- **Strategy modules** including smart-spread / imbalance logic, mean-reversion, arbitrage detection, and a 15-minute momentum-trap scanner.
- **AI/ML components** for liquidity scoring, market-regime detection, and strategy selection, plus XGBoost/scikit-learn based model support.
- **Execution pipeline** with order validation, response normalization, fill processing, order-state management, and exchange routing.
- **Portfolio and risk controls** covering exposure, position sizing, drawdown limits, pre-trade risk, kill-switch behavior, reconciliation, and cooldowns.
- **Backtesting and replay** with simulated execution, slippage and fee models, equity curves, performance metrics, replay clocks, and walk-forward components.
- **Runtime infrastructure** with an event bus, retries, rate limiting, recovery/failover, structured logging, state snapshots, and graceful shutdown.
- **Monitoring** through health endpoints, runtime metrics, trade logging, alerts, and Prometheus integration.
- **Deployment support** through Docker, Docker Compose, systemd, and Ansible templates.

## Architecture

```text
                         +----------------------+
                         |     Exchange APIs    |
                         | Binance / Bybit / OKX|
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         |      Market Feeds    |
                         | polling / normalized  |
                         +----------+-----------+
                                    |
                                    v
                    +-------------------------------+
                    | Strategy + AI/ML Signal Layer |
                    | trap / spread / regime /     |
                    | liquidity / strategy select  |
                    +---------------+---------------+
                                    |
                                    v
                    +-------------------------------+
                    |     Risk + Portfolio Layer   |
                    | exposure / sizing / guards   |
                    +---------------+---------------+
                                    |
                                    v
                    +-------------------------------+
                    |       Execution Pipeline     |
                    | validate -> route -> fill -> |
                    | state/reconcile               |
                    +---------------+---------------+
                                    |
                                    v
                    +-------------------------------+
                    | Persistence + Observability  |
                    | SQLite / health / metrics /  |
                    | reports / Prometheus          |
                    +-------------------------------+
```

## Project Structure

```text
.
├── ai/                    # Liquidity, regime, and strategy-selection modules
├── app/                   # Runtime container, runner, and settings
├── backtesting/           # Replay, simulation, fees, slippage, metrics
├── configs/               # YAML and safe environment templates
├── core/                  # Event bus, retries, state, recovery, routing
├── deploy/                # Ansible deployment templates
├── execution/             # Order validation and execution pipeline
├── feeds/                 # Exchange polling and market-data normalization
├── microservices/         # Runtime service components
├── models/                # Order, trade, position, signal, market-data models
├── monitoring/            # Health, metrics, alerts, Prometheus exporter
├── portfolio/             # Capital allocation, exposure, ledger, strategy weights
├── reports/               # Report generator and exported analytics
├── risk/                  # Kill switch, portfolio guard, pre-trade risk
├── scripts/               # Preflight, safety, maintenance, runtime helpers
├── strategies/            # Trading strategy implementations
├── tests/                 # Unit, integration, load, replay, and stress tests
├── main.py                # Unified CLI entry point
├── Dockerfile             # Container image
├── docker-compose.yml     # Runtime + Prometheus stack
├── aegis-pro.service      # systemd service unit
├── RUN_AEGIS_FORTRESS_PRO.ps1
├── requirements.txt
└── README.md
```

## Requirements

- Python **3.10+**
- Windows PowerShell or a Unix-like shell
- Internet access for exchange market-data/API connectivity
- Exchange API credentials only when using authenticated paper/testnet or live execution

The dependency list includes CCXT, NumPy, pandas, SciPy, XGBoost, scikit-learn, PyTorch, statsmodels, cryptography, Flask, psutil, aiohttp, Prometheus client libraries, pytest, Black, Ruff, and PyYAML.

## Windows Quick Start

From the project root:

```powershell
# Create virtual environment
py -3.10 -m venv .venv

# Install dependencies
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Create a safe local environment file
Copy-Item .\configs\fortress_low_capital.env.template .\.env

# Edit .env and keep AEGIS_MODE=PAPER while testing
notepad .env

# Compile the project
.\.venv\Scripts\python.exe main.py compile

# Run the test suite
.\.venv\Scripts\python.exe -m pytest -q

# Run preflight checks
.\.venv\Scripts\python.exe main.py --env-file .env preflight

# Start the runtime
.\.venv\Scripts\python.exe main.py --env-file .env run
```

### PowerShell launcher

The repository also includes a convenience launcher that creates the virtual environment, installs dependencies, runs compile/tests/safety checks, and starts the runtime:

```powershell
powershell -ExecutionPolicy Bypass -File .\RUN_AEGIS_FORTRESS_PRO.ps1
```

Open the local health endpoint after startup:

```text
http://127.0.0.1:8080/health
```

Metrics are exposed on the configured metrics port, normally `127.0.0.1:9000`.

## CLI Commands

`main.py` is the unified controller. Available commands include:

```text
python main.py run
python main.py preflight
python main.py readiness
python main.py test
python main.py compile
python main.py clean
python main.py freeze
python main.py doctor
python main.py verify
python main.py watch
python main.py profit
python main.py backtest-runtime <replay-file>
python main.py legacy [args...]
```

An environment file can be selected with:

```text
python main.py --env-file .env run
```

## Configuration Profiles

### Low-capital Fortress profile

`configs/fortress_low_capital.env.template` and `.env.low_capital.template` contain conservative starter settings intended for small-account experiments. These values are examples, not guarantees of profitability.

Create your local file with:

```powershell
Copy-Item .\configs\fortress_low_capital.env.template .\.env
```

### Production-style template

`.env.production.template` provides a broader configuration layout for exchange credentials, risk limits, persistence, monitoring, and live-strategy settings.

### Live trading gate

The runtime blocks LIVE mode unless the explicit confirmation variable is present:

```text
AEGIS_MODE=LIVE
AEGIS_LIVE_CONFIRM=YES_I_ACCEPT_THE_RISK
```

The repository also contains `scripts/live_safety_check.py`, which validates key live-mode conditions and enforces configurable order-size and daily-loss ceilings.

## Fortress Momentum-Trap Strategy

The Fortress addition is implemented as a modular service rather than a standalone loop. The scanner is designed around 15-minute candles and can combine signals such as:

- support break and reclaim,
- volume expansion,
- lower-wick rejection,
- EMA confirmation,
- MACD confirmation,
- RSI overextension filtering,
- Bollinger-band filtering.

The strategy can be enabled/configured through the environment variables documented in `configs/fortress_low_capital.env.template`.

## Risk and Safety

This repository is intended for controlled experimentation. Cryptocurrency trading can result in rapid and substantial losses.

Before any live execution:

1. Keep `AEGIS_MODE=PAPER` and verify the runtime first.
2. Use exchange API keys with **trading permissions only** and **withdrawal disabled**.
3. Start with small limits and validate minimum-notional, fee, spread, and slippage behavior on the selected exchange.
4. Check the health endpoint, logs, and risk rejections before enabling live execution.
5. Reconcile positions carefully after restarts or any manual exchange activity.

The project contains operational safeguards, but code-level safeguards cannot remove exchange outages, network failures, liquidity gaps, market shocks, unexpected fills, API changes, or other real-world failure modes.

## Backtesting and Reports

Backtesting components are under `backtesting/` and the legacy runtime also contains a `backtest.py` entry point.

Report generation is available under `reports/`:

```powershell
python reports/report_generator.py --daily
python reports/report_generator.py --weekly
python reports/report_generator.py --full
python reports/report_generator.py --csv
python reports/report_generator.py --all
```

Generated reports should remain local and are intentionally ignored by Git when treated as runtime artifacts.

## Testing and Code Quality

The repository is configured for pytest, Black, and Ruff.

```powershell
python -m pytest -q
python main.py compile
ruff check .
black --check .
```

Run the project readiness flow with:

```powershell
python main.py readiness
```

`readiness` compiles Python files, runs pytest, performs preflight checks, and can refresh frozen requirements on Windows.

## Docker

Build and start the runtime stack:

```powershell
docker compose build
docker compose up -d
```

Services:

| Service | Purpose | Default port |
|---|---|---:|
| `aegis-runtime` | Trading runtime and health server | 8080 |
| `aegis-runtime` | Prometheus metrics endpoint | 9000 |
| `prometheus` | Metrics collection UI/API | 9090 |

The compose file mounts `./data` and `./logs` for local runtime persistence and publishes the runtime/metrics ports.

## Linux / systemd

The repository includes `aegis-pro.service` and deployment templates under `deploy/new/`.

A typical systemd installation is:

```bash
sudo cp aegis-pro.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable aegis-pro
sudo systemctl start aegis-pro
journalctl -u aegis-pro -f
```

The Ansible playbook is documented in `deploy/new/playbook.yml`.

## Security / GitHub Hygiene

Do **not** commit credentials, local `.env` files, exchange API keys, database files, model binaries, logs, or runtime state.

The included `.gitignore` is configured to ignore common secret and runtime artifacts. Before the first push, always run:

```powershell
git status
```

and inspect staged files with:

```powershell
git diff --cached --name-only
```

The provided environment files are templates only and must contain no real credentials.

## Known Limitations

The included project documentation identifies several areas that are not equivalent to a fully autonomous institutional trading stack, including:

- RL training infrastructure is present as a dependency/module area but is not a complete end-to-end DQN/PPO training platform.
- Full Avellaneda–Stoikov style market making is not implemented.
- The live market-data path primarily relies on CCXT polling rather than a complete low-latency WebSocket execution architecture.
- The feature set is below a very large multi-source research pipeline; additional sentiment/on-chain data would require further integrations.
- Tick storage/replay infrastructure exists, while the backtesting path is primarily based on bar/replay components rather than a fully integrated tick-level production simulator.

See `docs/PRODUCTION_ROADMAP.md`, `docs/FORTRESS_PRO_UPGRADE.md`, and `docs/LIVE_AUDIT_REPORT.md` for project-specific implementation notes and remaining operational considerations.

## Project Status

The archive contains both current runtime code and compatibility/maintenance scripts. The root `main.py` is the unified entry point; `main_legacy.py` is retained for legacy compatibility.

For a first GitHub release, keep the repository focused on source/config templates/tests/documentation and exclude generated runtime artifacts and local backups.

## License

No open-source license file is included in this archive. Add a `LICENSE` file before publishing the repository under a specific open-source license.

## Disclaimer

This software is for educational, research, and controlled testing purposes. Nothing in this repository is financial advice, a recommendation to trade, or a guarantee of returns. Use at your own risk and comply with the rules and terms of the exchanges and services you use.
