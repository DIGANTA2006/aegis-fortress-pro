"""
monitor.py  -  AEGIS PRO v2
Telegram alerts + Flask real-time dashboard (CPU, equity, positions, signals).
Runs entirely in daemon threads - zero impact on trading loop.
"""

import logging
import threading
import time
from typing import Any, Dict, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import AegisConfig
from utils import format_usdt, now_iso

log = logging.getLogger("aegis.monitor")


# ---------------------------------------------------------------------------
# Optional deps
# ---------------------------------------------------------------------------

try:
    import psutil

    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

try:
    from flask import Flask, jsonify, render_template_string

    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False
    log.warning("flask not installed. Dashboard disabled. pip install flask")


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


class TelegramNotifier:
    """
    Thread-safe Telegram notifier with batching and retry.
    Messages are queued and flushed every 60 seconds (or when batch is full).
    """

    BATCH_SIZE = 5
    FLUSH_INTERVAL = 60.0

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self._queue: List[str] = []
        self._lock = threading.Lock()
        self._last_flush = time.time()
        self._session = self._build_session()

        if token and chat_id:
            t = threading.Thread(target=self._flush_loop, daemon=True, name="tg-flusher")
            t.start()

    @staticmethod
    def _build_session() -> requests.Session:
        s = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        s.mount("https://", HTTPAdapter(max_retries=retries))
        return s

    def send(self, msg: str, parse_mode: str = "HTML") -> None:
        """Queue a message for sending."""
        if not self.token or not self.chat_id:
            return
        with self._lock:
            self._queue.append(msg)
            if len(self._queue) >= self.BATCH_SIZE:
                self._flush_locked()

    def _flush_loop(self) -> None:
        while True:
            time.sleep(5)
            with self._lock:
                if self._queue and (time.time() - self._last_flush >= self.FLUSH_INTERVAL):
                    self._flush_locked()

    def _flush_locked(self) -> None:
        """Must be called with self._lock held."""
        if not self._queue:
            return
        batch = "\n\n".join(self._queue)
        self._queue.clear()
        self._last_flush = time.time()
        threading.Thread(target=self._send_now, args=(batch,), daemon=True, name="tg-send").start()

    def flush_all(self) -> None:
        """Force-flush on shutdown."""
        with self._lock:
            self._flush_locked()

    def _send_now(self, text: str) -> None:
        if not text.strip():
            return
        # Telegram max 4096 chars
        for chunk in [text[i : i + 4000] for i in range(0, len(text), 4000)]:
            try:
                url = f"https://api.telegram.org/bot{self.token}/sendMessage"
                resp = self._session.post(
                    url,
                    data={"chat_id": self.chat_id, "text": chunk, "parse_mode": "HTML"},
                    timeout=10,
                )
                resp.raise_for_status()
            except Exception as exc:
                log.warning(f"Telegram send failed: {exc}")

    # ---- Convenience formatters ----

    def trade_entry(self, symbol: str, price: float, qty: float, signal: str, mode: str) -> None:
        icon = "Ã°Å¸Å¸Â¢" if mode == "LIVE" else "Ã°Å¸Å¸Â¡"
        self.send(
            f"{icon} <b>ENTRY</b> {symbol}\n"
            f"Signal: {signal}\n"
            f"Price: <code>{price:.6g}</code>  Qty: <code>{qty:.6g}</code>\n"
            f"Mode: {mode}"
        )

    def trade_exit(
        self, symbol: str, price: float, qty: float, pnl: float, reason: str, mode: str
    ) -> None:
        icon = "[PROFIT]" if pnl >= 0 else "[LOSS]"
        sign = "+" if pnl >= 0 else ""
        self.send(
            f"{icon} <b>EXIT</b> {symbol}  [{reason}]\n"
            f"Price: <code>{price:.6g}</code>  Qty: <code>{qty:.6g}</code>\n"
            f"PnL: <b>{sign}{pnl:.2f} USDT</b>\n"
            f"Mode: {mode}"
        )

    def drawdown_alert(self, pct: float, equity: float) -> None:
        self.send(
            f"Ã¢Å¡Â Ã¯Â¸Â <b>DRAWDOWN ALERT</b>\n"
            f"Drawdown: <b>{pct:.2f}%</b>\n"
            f"Equity: {format_usdt(equity)}"
        )

    def daily_summary(self, trades: int, wins: int, losses: int, pnl: float, equity: float) -> None:
        self.send(
            f"[DAILY SUMMARY] <b>Daily Summary</b>`n"
            f"Trades: {trades}  Wins: {wins}  Losses: {losses}\n"
            f"PnL: {format_usdt(pnl)}\n"
            f"Equity: {format_usdt(equity)}"
        )

    def error_alert(self, context: str, error: str) -> None:
        self.send(f"Ã°Å¸Å¡Â¨ <b>ERROR</b> [{context}]\n<code>{error[:300]}</code>")

    def system_info(self, msg: str) -> None:
        self.send(f"Ã¢â€žÂ¹Ã¯Â¸Â {msg}")


# ---------------------------------------------------------------------------
# Shared state for the dashboard (updated by main loop)
# ---------------------------------------------------------------------------

_dashboard_state: Dict[str, Any] = {
    "status": "starting",
    "equity": 0.0,
    "positions": {},
    "recent_signals": [],
    "daily_pnl": 0.0,
    "total_trades": 0,
    "win_rate": 0.0,
    "cpu_pct": 0.0,
    "mem_mb": 0.0,
    "uptime_secs": 0.0,
    "last_updated": "",
}
_state_lock = threading.Lock()
_start_time = time.time()


def update_dashboard_state(**kwargs) -> None:
    """Called by main loop to push fresh data to dashboard."""
    with _state_lock:
        _dashboard_state.update(kwargs)
        _dashboard_state["uptime_secs"] = time.time() - _start_time
        _dashboard_state["last_updated"] = now_iso()
        if _HAS_PSUTIL:
            _dashboard_state["cpu_pct"] = psutil.cpu_percent(interval=None)
            proc = psutil.Process()
            _dashboard_state["mem_mb"] = proc.memory_info().rss / (1024 * 1024)


# ---------------------------------------------------------------------------
# Flask dashboard
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="10">
<title>AEGIS PRO Dashboard</title>
<style>
  body { font-family: monospace; background:#0d1117; color:#c9d1d9; padding:20px; }
  h1 { color:#58a6ff; } h2 { color:#79c0ff; border-bottom:1px solid #30363d; }
  table { border-collapse:collapse; width:100%; margin-bottom:20px; }
  th { background:#161b22; color:#58a6ff; padding:8px; text-align:left; }
  td { padding:6px 8px; border-top:1px solid #21262d; }
  .pos { color:#3fb950; } .neg { color:#f85149; }
  .badge { padding:2px 8px; border-radius:4px; font-size:0.85em; }
  .live { background:#1f4d2a; color:#3fb950; }
  .paper { background:#4d3800; color:#e3b341; }
  .stat { background:#161b22; padding:10px; margin:5px; display:inline-block; min-width:140px; border-radius:6px; }
  .stat-label { font-size:0.75em; color:#8b949e; }
  .stat-val { font-size:1.4em; color:#c9d1d9; }
</style>
</head>
<body>
<h1>Ã¢Å¡Â¡ AEGIS PRO  <span class="badge {{ 'live' if state.status == 'ONLINE' else 'paper' }}">{{ state.status }}</span></h1>

<div>
  <div class="stat"><div class="stat-label">EQUITY</div><div class="stat-val">${{ "%.2f"|format(state.equity) }}</div></div>
  <div class="stat"><div class="stat-label">DAILY PnL</div>
    <div class="stat-val {{ 'pos' if state.daily_pnl >= 0 else 'neg' }}">${{ "%+.2f"|format(state.daily_pnl) }}</div></div>
  <div class="stat"><div class="stat-label">TRADES TODAY</div><div class="stat-val">{{ state.total_trades }}</div></div>
  <div class="stat"><div class="stat-label">WIN RATE</div><div class="stat-val">{{ "%.1f"|format(state.win_rate * 100) }}%</div></div>
  <div class="stat"><div class="stat-label">CPU</div><div class="stat-val">{{ "%.1f"|format(state.cpu_pct) }}%</div></div>
  <div class="stat"><div class="stat-label">MEM</div><div class="stat-val">{{ "%.0f"|format(state.mem_mb) }} MB</div></div>
  <div class="stat"><div class="stat-label">UPTIME</div>
    <div class="stat-val">{{ "%dh %dm"|format(state.uptime_secs // 3600, (state.uptime_secs % 3600) // 60) }}</div></div>
</div>

<h2>Open Positions</h2>
{% if state.positions %}
<table>
<tr><th>Symbol</th><th>Entry</th><th>Current</th><th>Qty</th><th>PnL</th><th>Stop</th><th>TP1</th><th>TP2</th></tr>
{% for sym, p in state.positions.items() %}
<tr>
  <td>{{ sym }}</td>
  <td><code>{{ "%.6g"|format(p.entry_price) }}</code></td>
  <td><code>{{ "%.6g"|format(p.get("current_price", p.entry_price)) }}</code></td>
  <td><code>{{ "%.4g"|format(p.qty) }}</code></td>
  <td class="{{ 'pos' if p.get('unrealised_pnl', 0) >= 0 else 'neg' }}">${{ "%+.2f"|format(p.get("unrealised_pnl", 0)) }}</td>
  <td><code>{{ "%.6g"|format(p.stop_loss) }}</code></td>
  <td><code>{{ "%.6g"|format(p.tp1) }}</code></td>
  <td><code>{{ "%.6g"|format(p.tp2) }}</code></td>
</tr>
{% endfor %}
</table>
{% else %}
<p style="color:#8b949e">No open positions.</p>
{% endif %}

<h2>Recent Signals</h2>
<table>
<tr><th>Time</th><th>Symbol</th><th>Type</th><th>ML Prob</th><th>Fused</th><th>Action</th></tr>
{% for s in state.recent_signals[-10:]|reverse %}
<tr>
  <td>{{ s.ts }}</td><td>{{ s.symbol }}</td><td>{{ s.signal_type }}</td>
  <td>{{ "%.2f"|format(s.ml_prob) }}</td>
  <td>{{ "%.2f"|format(s.fused_prob) }}</td>
  <td>{{ s.action }}</td>
</tr>
{% endfor %}
</table>

<p style="color:#484f58;font-size:0.8em">Last updated: {{ state.last_updated }}</p>
</body>
</html>
"""


def _create_flask_app() -> "Flask":
    app = Flask("aegis_dashboard")

    @app.route("/")
    def index():
        with _state_lock:
            state = dict(_dashboard_state)
        return render_template_string(_DASHBOARD_HTML, state=state)

    @app.route("/api/state")
    def api_state():
        with _state_lock:
            return jsonify(_dashboard_state)

    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok", "ts": now_iso()})

    return app


def start_dashboard(cfg: AegisConfig) -> None:
    """Start Flask in a daemon thread. No-op if flask not installed."""
    if not _HAS_FLASK or not cfg.dashboard_enabled:
        log.info("Dashboard disabled (flask not installed or dashboard_enabled=False).")
        return

    app = _create_flask_app()

    def _run():
        import logging as _logging

        _logging.getLogger("werkzeug").setLevel(_logging.ERROR)
        app.run(
            host=cfg.dashboard_host,
            port=cfg.dashboard_port,
            debug=False,
            use_reloader=False,
        )

    t = threading.Thread(target=_run, daemon=True, name="flask-dashboard")
    t.start()
    log.info(f"Dashboard started at http://{cfg.dashboard_host}:{cfg.dashboard_port}")
