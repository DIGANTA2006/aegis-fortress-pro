import html
import json
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


class HealthServer:
    def __init__(
        self,
        host: str,
        port: int,
        status_provider,
    ) -> None:
        self.host = host
        self.port = port
        self.status_provider = status_provider

        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return

        provider = self.status_provider

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = urlparse(self.path).path

                if path in {"/health", "/ready", "/api/state"}:
                    payload = provider()
                    status_code = 200 if payload.get("healthy") else 503
                    self._send_json(payload, status_code)
                    return

                if path == "/api/summary":
                    payload = provider()
                    self._send_json(self._summary(payload), 200)
                    return

                if path == "/api/logs":
                    self._send_json({"logs": self._tail_logs()}, 200)
                    return

                if path in {"/", "/dashboard"}:
                    self._send_html(self._dashboard_html())
                    return

                if path == "/logs":
                    self._send_html(self._logs_html())
                    return

                self.send_response(404)
                self.end_headers()

            def _send_json(self, payload, status_code: int = 200):
                body = json.dumps(
                    payload,
                    indent=2,
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")

                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_html(self, body: str, status_code: int = 200):
                encoded = body.encode("utf-8")

                self.send_response(status_code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _service_metrics(self, state: dict, service_name: str) -> dict:
                return (
                    state.get("runtime", {})
                    .get("services", {})
                    .get(service_name, {})
                    .get("metrics", {})
                )

            def _summary(self, state: dict) -> dict:
                market = self._service_metrics(state, "market-data-service")
                strategy_service = self._service_metrics(state, "live-strategy-service")
                strategy = strategy_service.get("strategy", {})
                execution = self._service_metrics(state, "execution-service")
                risk = self._service_metrics(state, "risk-service")

                ticks = int(market.get("ticks_published", 0) or 0)
                orderbooks = int(market.get("orderbooks_published", 0) or 0)

                return {
                    "healthy": bool(state.get("healthy", False)),
                    "captured_at": state.get("captured_at"),
                    "runtime_running": bool(
                        state.get("runtime", {}).get("running", False)
                    ),
                    "database_up": bool(
                        state.get("database", {}).get("up", False)
                    ),
                    "kill_switch_triggered": bool(
                        state.get("kill_switch", {}).get("triggered", False)
                    ),
                    "daily_pnl": state.get("kill_switch", {}).get("daily_pnl", 0.0),
                    "market_packets_total": ticks + orderbooks,
                    "ticks_published": ticks,
                    "orderbooks_published": orderbooks,
                    "normalization_failures": int(
                        market.get("normalization_failures", 0) or 0
                    ),
                    "strategy_ticks_seen": int(
                        strategy.get("ticks_seen", 0) or 0
                    ),
                    "strategy_orderbooks_seen": int(
                        strategy.get("orderbooks_seen", 0) or 0
                    ),
                    "signals_generated": int(
                        strategy.get("signals_generated", 0) or 0
                    ),
                    "entries_generated": int(
                        strategy.get("entries_generated", 0) or 0
                    ),
                    "exits_generated": int(
                        strategy.get("exits_generated", 0) or 0
                    ),
                    "take_profit_exits": int(
                        strategy.get("take_profit_exits_generated", 0) or 0
                    ),
                    "stop_loss_exits": int(
                        strategy.get("stop_loss_exits_generated", 0) or 0
                    ),
                    "time_exits": int(
                        strategy.get("time_exits_generated", 0) or 0
                    ),
                    "order_requests_published": int(
                        strategy_service.get("order_requests_published", 0) or 0
                    ),
                    "execution_received": int(
                        execution.get("received_requests", 0) or 0
                    ),
                    "execution_accepted": int(
                        execution.get("accepted_requests", 0) or 0
                    ),
                    "execution_rejected": int(
                        execution.get("rejected_requests", 0) or 0
                    ),
                    "execution_failed": int(
                        execution.get("failed_requests", 0) or 0
                    ),
                    "risk_events_emitted": int(
                        risk.get("risk_events_emitted", 0) or 0
                    ),
                    "critical_breaches": int(
                        risk.get("critical_breaches", 0) or 0
                    ),
                    "skipped_for_insufficient_data": int(
                        strategy.get("skipped_for_insufficient_data", 0) or 0
                    ),
                    "skipped_for_cooldown": int(
                        strategy.get("skipped_for_cooldown", 0) or 0
                    ),
                    "skipped_for_spread": int(
                        strategy.get("skipped_for_spread", 0) or 0
                    ),
                    "blocked_symbols": int(
                        strategy.get("blocked_symbols", 0) or 0
                    ),
                }

            def _tail_logs(self, max_lines: int = 260):
                log_files = [
                    Path("logs/aegis_runtime.jsonl"),
                    Path("logs/aegis.log"),
                    Path("logs/risk_events.jsonl"),
                ]

                output = []

                for log_file in log_files:
                    if not log_file.exists():
                        continue

                    try:
                        lines = log_file.read_text(
                            encoding="utf-8",
                            errors="replace",
                        ).splitlines()

                        output.append(f"===== {log_file.as_posix()} =====")
                        output.extend(lines[-max_lines:])
                        output.append("")
                    except Exception as exc:
                        output.append(
                            f"Could not read {log_file.as_posix()}: {exc}"
                        )

                if not output:
                    output.append("No logs found yet.")

                return "\n".join(output)

            def _style(self):
                return """
                <style>
                    * { box-sizing: border-box; }
                    body {
                        background: #07111f;
                        color: #e5eefc;
                        font-family: Consolas, monospace;
                        margin: 0;
                    }
                    header {
                        background: #0f1f33;
                        padding: 18px 26px;
                        border-bottom: 1px solid #263b55;
                        position: sticky;
                        top: 0;
                        z-index: 10;
                    }
                    h1 { margin: 0; font-size: 24px; }
                    h2 { color: #93c5fd; }
                    nav { margin-top: 10px; }
                    a {
                        color: #7dd3fc;
                        margin-right: 18px;
                        text-decoration: none;
                    }
                    main { padding: 22px; }
                    .grid {
                        display: grid;
                        grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
                        gap: 14px;
                        margin-bottom: 22px;
                    }
                    .card {
                        background: #0f1f33;
                        border: 1px solid #263b55;
                        border-radius: 12px;
                        padding: 16px;
                    }
                    .label {
                        color: #94a3b8;
                        font-size: 13px;
                    }
                    .value {
                        font-size: 28px;
                        font-weight: bold;
                        margin-top: 8px;
                    }
                    .ok { color: #22c55e; }
                    .bad { color: #ef4444; }
                    .warn { color: #f59e0b; }
                    pre {
                        white-space: pre-wrap;
                        word-break: break-word;
                        background: #020617;
                        border: 1px solid #263b55;
                        border-radius: 12px;
                        padding: 16px;
                        max-height: 72vh;
                        overflow: auto;
                    }
                    button {
                        background: #2563eb;
                        color: white;
                        border: none;
                        padding: 10px 14px;
                        border-radius: 8px;
                        cursor: pointer;
                    }
                    .muted { color: #94a3b8; }
                </style>
                """

            def _dashboard_html(self):
                return """
                <!doctype html>
                <html>
                <head>
                    <title>AEGIS Metrics Dashboard</title>
                """ + self._style() + """
                </head>
                <body>
                    <header>
                        <h1>AEGIS Metrics Dashboard</h1>
                        <nav>
                            <a href="/dashboard">Dashboard</a>
                            <a href="/logs">Logs</a>
                            <a href="/api/summary">Summary JSON</a>
                            <a href="/api/state">Full State JSON</a>
                        </nav>
                    </header>

                    <main>
                        <div class="grid" id="cards"></div>

                        <button onclick="loadDashboard()">Refresh Now</button>
                        <span class="muted">Auto refresh every 5 seconds.</span>

                        <h2>Summary JSON</h2>
                        <pre id="summary">Loading...</pre>
                    </main>

                    <script>
                        function card(label, value, cssClass = "") {
                            return `
                                <div class="card">
                                    <div class="label">${label}</div>
                                    <div class="value ${cssClass}">${value}</div>
                                </div>
                            `;
                        }

                        function yesNo(value) {
                            return value ? "YES" : "NO";
                        }

                        async function loadDashboard() {
                            const res = await fetch('/api/summary');
                            const data = await res.json();

                            const cards = [
                                card("Runtime Running", yesNo(data.runtime_running), data.runtime_running ? "ok" : "bad"),
                                card("Database Up", yesNo(data.database_up), data.database_up ? "ok" : "bad"),
                                card("Kill Switch Triggered", yesNo(data.kill_switch_triggered), data.kill_switch_triggered ? "bad" : "ok"),
                                card("Daily PnL", data.daily_pnl),

                                card("Market Packets Total", data.market_packets_total),
                                card("Ticker Packets Seen", data.ticks_published),
                                card("Orderbook Packets Seen", data.orderbooks_published),
                                card("Normalization Failures", data.normalization_failures, data.normalization_failures > 0 ? "warn" : "ok"),

                                card("Strategy Ticks Seen", data.strategy_ticks_seen),
                                card("Strategy Orderbooks Seen", data.strategy_orderbooks_seen),
                                card("Signals Generated", data.signals_generated),
                                card("Entry Signals", data.entries_generated),

                                card("Exit Signals", data.exits_generated),
                                card("Take Profit Exits", data.take_profit_exits),
                                card("Stop Loss Exits", data.stop_loss_exits),
                                card("Time Exits", data.time_exits),

                                card("Order Requests Published", data.order_requests_published),
                                card("Execution Requests", data.execution_received),
                                card("Accepted Orders", data.execution_accepted, data.execution_accepted > 0 ? "ok" : ""),
                                card("Rejected Orders", data.execution_rejected, data.execution_rejected > 0 ? "warn" : ""),

                                card("Failed Orders", data.execution_failed, data.execution_failed > 0 ? "bad" : "ok"),
                                card("Risk Events", data.risk_events_emitted),
                                card("Critical Breaches", data.critical_breaches, data.critical_breaches > 0 ? "bad" : "ok"),
                                card("Blocked Symbols", data.blocked_symbols),

                                card("Skipped: Insufficient Data", data.skipped_for_insufficient_data),
                                card("Skipped: Cooldown", data.skipped_for_cooldown),
                                card("Skipped: Spread", data.skipped_for_spread)
                            ];

                            document.getElementById("cards").innerHTML = cards.join("");
                            document.getElementById("summary").textContent =
                                JSON.stringify(data, null, 2);
                        }

                        loadDashboard();
                        setInterval(loadDashboard, 5000);
                    </script>
                </body>
                </html>
                """

            def _logs_html(self):
                safe_logs = html.escape(self._tail_logs())
                return """
                <!doctype html>
                <html>
                <head>
                    <title>AEGIS Logs</title>
                """ + self._style() + """
                </head>
                <body>
                    <header>
                        <h1>AEGIS Logs</h1>
                        <nav>
                            <a href="/dashboard">Dashboard</a>
                            <a href="/logs">Logs</a>
                            <a href="/api/summary">Summary JSON</a>
                            <a href="/api/state">Full State JSON</a>
                        </nav>
                    </header>

                    <main>
                        <button onclick="loadLogs()">Refresh Logs</button>
                        <span class="muted">Auto refresh every 5 seconds.</span>
                        <pre id="logs">""" + safe_logs + """</pre>
                    </main>

                    <script>
                        async function loadLogs() {
                            const res = await fetch('/api/logs');
                            const data = await res.json();
                            document.getElementById("logs").textContent = data.logs;
                        }

                        setInterval(loadLogs, 5000);
                    </script>
                </body>
                </html>
                """

            def log_message(self, format, *args):
                return None

        self._server = ThreadingHTTPServer(
            (self.host, self.port),
            Handler,
        )

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="aegis-health-server",
            daemon=True,
        )

        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return

        self._server.shutdown()
        self._server.server_close()

        self._server = None
        self._thread = None
