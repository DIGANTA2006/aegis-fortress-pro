"""
reports/report_generator.py  –  AEGIS PRO v2
Generates HTML and CSV performance reports from the aegis.db database.

Reports produced:
  - daily_report_YYYYMMDD.html   : daily PnL, trade log, equity chart
  - weekly_report_YYYY_WNN.html  : weekly summary with win-rate, Sharpe, drawdown
  - full_report.html             : full trade history with filters and statistics
  - trades_export.csv            : raw trade CSV for external analysis

Run standalone:
    python reports/report_generator.py --daily
    python reports/report_generator.py --weekly
    python reports/report_generator.py --full
    python reports/report_generator.py --all
    python reports/report_generator.py --csv
"""

import argparse
import logging
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("aegis.reports")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).parent
_DATA_DIR = _THIS_DIR.parent
_DB_PATH = _DATA_DIR / "aegis.db"
_REPORT_DIR = _THIS_DIR  # reports/ lives here


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _connect() -> sqlite3.Connection:
    if not _DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {_DB_PATH}")
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _query(sql: str, params: tuple = ()) -> list[dict]:
    conn = _connect()
    try:
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def _sharpe(returns: list[float], rf: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns) - rf
    std = math.sqrt(sum((r - mean - rf) ** 2 for r in returns) / (len(returns) - 1))
    return (mean / std * math.sqrt(252)) if std > 0 else 0.0


def _max_drawdown(equity_vals: list[float]) -> float:
    """Returns max drawdown as a percentage (0–100)."""
    if not equity_vals:
        return 0.0
    peak = equity_vals[0]
    max_dd = 0.0
    for v in equity_vals:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _profit_factor(trades: list[dict]) -> float:
    gross_win = sum(t["pnl"] for t in trades if t.get("pnl") and t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t.get("pnl") and t["pnl"] < 0))
    return gross_win / gross_loss if gross_loss > 0 else float("inf")


def _compute_stats(trades: list[dict]) -> dict:
    closed = [t for t in trades if t.get("pnl") is not None and t["action"] != "BUY"]
    wins = [t for t in closed if t["pnl"] > 0]
    losses = [t for t in closed if t["pnl"] <= 0]

    total_pnl = sum(t["pnl"] for t in closed)
    total_fees = sum(t.get("fees", 0) or 0 for t in closed)
    returns = [t["pnl"] for t in closed]

    stats = {
        "total_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed) * 100 if closed else 0.0,
        "total_pnl": total_pnl,
        "avg_pnl": total_pnl / len(closed) if closed else 0.0,
        "total_fees": total_fees,
        "net_pnl": total_pnl - total_fees,
        "avg_win": sum(t["pnl"] for t in wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(t["pnl"] for t in losses) / len(losses) if losses else 0.0,
        "largest_win": max((t["pnl"] for t in wins), default=0.0),
        "largest_loss": min((t["pnl"] for t in losses), default=0.0),
        "profit_factor": _profit_factor(closed),
        "sharpe": _sharpe(returns),
        "avg_r": sum(t.get("r_multiple", 0) or 0 for t in closed) / len(closed) if closed else 0.0,
    }
    return stats


# ---------------------------------------------------------------------------
# HTML template helpers
# ---------------------------------------------------------------------------

_CSS = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', monospace;
         background: #0d1117; color: #c9d1d9; padding: 24px; }
  h1  { color: #58a6ff; margin-bottom: 6px; }
  h2  { color: #79c0ff; border-bottom: 1px solid #30363d; padding-bottom: 6px;
         margin: 24px 0 12px; }
  p.sub { color: #8b949e; font-size: 0.85em; margin-bottom: 20px; }
  .stats-grid { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 20px; }
  .stat { background: #161b22; border: 1px solid #30363d; border-radius: 6px;
          padding: 12px 18px; min-width: 140px; }
  .stat-label { font-size: 0.72em; color: #8b949e; text-transform: uppercase;
                letter-spacing: 0.05em; }
  .stat-val   { font-size: 1.4em; color: #c9d1d9; margin-top: 4px; font-weight: 600; }
  .pos { color: #3fb950; } .neg { color: #f85149; } .neu { color: #79c0ff; }
  table { width: 100%; border-collapse: collapse; font-size: 0.88em; margin-bottom: 20px; }
  th { background: #161b22; color: #58a6ff; padding: 8px 10px; text-align: left;
       border-bottom: 2px solid #30363d; }
  td { padding: 6px 10px; border-top: 1px solid #21262d; }
  tr:hover td { background: #161b22; }
  .badge { padding: 2px 7px; border-radius: 4px; font-size: 0.8em; font-weight: 600; }
  .live  { background: #1f4d2a; color: #3fb950; }
  .paper { background: #4d3800; color: #e3b341; }
  footer { margin-top: 30px; color: #484f58; font-size: 0.78em; }
</style>
"""


def _stat_card(label: str, value: str, cls: str = "") -> str:
    return (
        f'<div class="stat"><div class="stat-label">{label}</div>'
        f'<div class="stat-val {cls}">{value}</div></div>'
    )


def _fmt_pnl(v: float) -> str:
    cls = "pos" if v >= 0 else "neg"
    sign = "+" if v >= 0 else ""
    return f'<span class="{cls}">{sign}${v:,.2f}</span>'


def _fmt_pct(v: float) -> str:
    cls = "pos" if v >= 0 else "neg"
    sign = "+" if v >= 0 else ""
    return f'<span class="{cls}">{sign}{v:.1f}%</span>'


def _trade_table(trades: list[dict], max_rows: int = 200) -> str:
    if not trades:
        return "<p style='color:#8b949e'>No trades found.</p>"

    rows_html = []
    for t in trades[:max_rows]:
        pnl = t.get("pnl")
        pnl_cell = _fmt_pnl(pnl) if pnl is not None else "—"
        r = t.get("r_multiple")
        r_cell = f'<span class="{"pos" if r and r >= 0 else "neg"}">{r:+.2f}R</span>' if r else "—"
        mode = t.get("mode", "PAPER")
        mode_badge = f'<span class="badge {"live" if mode == "LIVE" else "paper"}">{mode}</span>'
        ml = t.get("ml_prob")
        ml_cell = f"{ml:.2f}" if ml else "—"
        rows_html.append(
            f"<tr>"
            f"<td>{t.get('ts', '')[:19]}</td>"
            f"<td><b>{t.get('symbol', '')}</b></td>"
            f"<td>{t.get('action', '')}</td>"
            f"<td>{t.get('signal_type', '') or '—'}</td>"
            f"<td><code>{t.get('price', 0):.6g}</code></td>"
            f"<td><code>{t.get('qty', 0):.4g}</code></td>"
            f"<td>{pnl_cell}</td>"
            f"<td>{r_cell}</td>"
            f"<td>{ml_cell}</td>"
            f"<td>{mode_badge}</td>"
            f"</tr>"
        )
    header = (
        "<table><thead><tr>"
        "<th>Time</th><th>Symbol</th><th>Action</th><th>Signal</th>"
        "<th>Price</th><th>Qty</th><th>PnL</th><th>R</th><th>ML P</th><th>Mode</th>"
        "</tr></thead><tbody>"
    )
    note = (
        f"<p class='sub'>Showing {min(len(trades), max_rows)} of {len(trades)} trades</p>"
        if len(trades) > max_rows
        else ""
    )
    return header + "".join(rows_html) + "</tbody></table>" + note


def _equity_sparkline(equity_data: list[dict]) -> str:
    """Simple inline SVG equity curve."""
    if len(equity_data) < 2:
        return ""
    vals = [float(e["equity"]) for e in equity_data]
    lo, hi = min(vals), max(vals)
    rng = max(hi - lo, 1)
    W, H = 800, 160
    pts = []
    for i, v in enumerate(vals):
        x = i / (len(vals) - 1) * W
        y = H - (v - lo) / rng * H
        pts.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(pts)
    color = "#3fb950" if vals[-1] >= vals[0] else "#f85149"
    return (
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;max-width:{W}px;height:{H}px;background:#161b22;'
        f'border-radius:6px;margin-bottom:20px">'
        f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="1.8"/>'
        f"</svg>"
    )


def _html_page(title: str, subtitle: str, body: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        "<!DOCTYPE html><html lang='en'><head>"
        f"<meta charset='utf-8'><title>{title}</title>{_CSS}"
        "</head><body>"
        f"<h1>⚡ AEGIS PRO – {title}</h1>"
        f"<p class='sub'>{subtitle} &nbsp;|&nbsp; Generated: {now}</p>"
        f"{body}"
        f"<footer>AEGIS PRO v2 &nbsp;·&nbsp; {now}</footer>"
        "</body></html>"
    )


# ---------------------------------------------------------------------------
# Report builders
# ---------------------------------------------------------------------------


def build_daily_report(date: str | None = None) -> Path:
    """
    Generate daily performance report for a given UTC date (YYYY-MM-DD).
    Defaults to today.
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    date_start = f"{date}T00:00:00Z"
    date_end = f"{date}T23:59:59Z"

    trades = _query(
        "SELECT * FROM trades WHERE ts >= ? AND ts <= ? ORDER BY ts",
        (date_start, date_end),
    )
    equity = _query(
        "SELECT * FROM equity_curve WHERE ts >= ? AND ts <= ? ORDER BY ts",
        (date_start, date_end),
    )

    stats = _compute_stats(trades)
    eq_vals = [float(e["equity"]) for e in equity]
    start_eq = eq_vals[0] if eq_vals else 0.0
    end_eq = eq_vals[-1] if eq_vals else 0.0
    daily_return_pct = (end_eq - start_eq) / start_eq * 100 if start_eq > 0 else 0.0
    max_dd = _max_drawdown(eq_vals)

    cards = (
        _stat_card("DATE", date)
        + _stat_card(
            "TOTAL PnL",
            f"{'+'if stats['total_pnl']>=0 else ''}${stats['total_pnl']:,.2f}",
            "pos" if stats["total_pnl"] >= 0 else "neg",
        )
        + _stat_card(
            "NET PnL",
            f"{'+'if stats['net_pnl']>=0 else ''}${stats['net_pnl']:,.2f}",
            "pos" if stats["net_pnl"] >= 0 else "neg",
        )
        + _stat_card("TRADES", str(stats["total_trades"]))
        + _stat_card(
            "WIN RATE", f"{stats['win_rate']:.1f}%", "pos" if stats["win_rate"] >= 50 else "neg"
        )
        + _stat_card("AVG WIN", f"${stats['avg_win']:,.2f}", "pos")
        + _stat_card("AVG LOSS", f"${stats['avg_loss']:,.2f}", "neg")
        + _stat_card(
            "PROFIT FACTOR",
            f"{stats['profit_factor']:.2f}" if math.isfinite(stats["profit_factor"]) else "∞",
            "pos" if stats["profit_factor"] >= 1.5 else "neg",
        )
        + _stat_card("FEES", f"${stats['total_fees']:,.2f}", "neg")
        + _stat_card(
            "DAILY RETURN",
            f"{'+'if daily_return_pct>=0 else ''}{daily_return_pct:.2f}%",
            "pos" if daily_return_pct >= 0 else "neg",
        )
        + _stat_card("MAX DRAWDOWN", f"{max_dd:.2f}%", "neg" if max_dd > 3 else "neu")
        + _stat_card("END EQUITY", f"${end_eq:,.2f}")
    )

    body = f'<div class="stats-grid">{cards}</div>' f"<h2>Equity Curve</h2>" + _equity_sparkline(
        equity
    ) + "<h2>Trade Log</h2>" + _trade_table(trades)

    out_path = _REPORT_DIR / f"daily_report_{date.replace('-', '')}.html"
    out_path.write_text(_html_page(f"Daily Report – {date}", f"{date}", body), encoding="utf-8")
    log.info(f"Daily report → {out_path.name}")
    return out_path


def build_weekly_report(year: int | None = None, week: int | None = None) -> Path:
    """
    Generate weekly performance report. Defaults to current ISO week.
    """
    now = datetime.now(timezone.utc)
    if year is None or week is None:
        iso = now.isocalendar()
        year, week = iso[0], iso[1]

    # ISO week: Monday to Sunday
    monday = datetime.fromisocalendar(year, week, 1).replace(tzinfo=timezone.utc)
    sunday = monday + timedelta(days=6, hours=23, minutes=59, seconds=59)
    date_start = monday.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_end = sunday.strftime("%Y-%m-%dT%H:%M:%SZ")

    trades = _query(
        "SELECT * FROM trades WHERE ts >= ? AND ts <= ? ORDER BY ts",
        (date_start, date_end),
    )
    equity = _query(
        "SELECT * FROM equity_curve WHERE ts >= ? AND ts <= ? ORDER BY ts",
        (date_start, date_end),
    )
    perf = _query(
        "SELECT * FROM performance WHERE date >= ? AND date <= ? ORDER BY date",
        (monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")),
    )

    stats = _compute_stats(trades)
    eq_vals = [float(e["equity"]) for e in equity]
    start_eq = eq_vals[0] if eq_vals else 0.0
    end_eq = eq_vals[-1] if eq_vals else 0.0
    weekly_return_pct = (end_eq - start_eq) / start_eq * 100 if start_eq > 0 else 0.0
    max_dd = _max_drawdown(eq_vals)

    # Daily breakdown table
    daily_rows = ""
    for row in perf:
        pnl = row.get("pnl_usdt", 0) or 0
        wr = (row.get("win_rate", 0) or 0) * 100
        daily_rows += (
            f"<tr><td>{row['date']}</td>"
            f"<td>{row.get('trades', 0)}</td>"
            f"<td>{row.get('wins', 0)}</td>"
            f"<td>{row.get('losses', 0)}</td>"
            f"<td>{_fmt_pnl(pnl)}</td>"
            f"<td>{wr:.1f}%</td>"
            f"<td>{row.get('expectancy', 0):.3f}R</td></tr>"
        )
    daily_table = (
        "<table><thead><tr><th>Date</th><th>Trades</th><th>Wins</th><th>Losses</th>"
        "<th>PnL</th><th>Win Rate</th><th>Expectancy</th></tr></thead>"
        f"<tbody>{daily_rows}</tbody></table>"
    )

    cards = (
        _stat_card("WEEK", f"{year} W{week:02d}")
        + _stat_card(
            "NET PnL",
            f"{'+'if stats['net_pnl']>=0 else ''}${stats['net_pnl']:,.2f}",
            "pos" if stats["net_pnl"] >= 0 else "neg",
        )
        + _stat_card("TOTAL TRADES", str(stats["total_trades"]))
        + _stat_card(
            "WIN RATE", f"{stats['win_rate']:.1f}%", "pos" if stats["win_rate"] >= 50 else "neg"
        )
        + _stat_card(
            "SHARPE (ann)", f"{stats['sharpe']:.2f}", "pos" if stats["sharpe"] >= 1 else "neg"
        )
        + _stat_card(
            "PROFIT FACTOR",
            f"{stats['profit_factor']:.2f}" if math.isfinite(stats["profit_factor"]) else "∞",
            "pos" if stats["profit_factor"] >= 1.5 else "neg",
        )
        + _stat_card("MAX DRAWDOWN", f"{max_dd:.2f}%", "neg" if max_dd > 5 else "neu")
        + _stat_card(
            "WEEKLY RETURN",
            f"{'+'if weekly_return_pct>=0 else ''}{weekly_return_pct:.2f}%",
            "pos" if weekly_return_pct >= 0 else "neg",
        )
        + _stat_card("AVG R", f"{stats['avg_r']:+.3f}R", "pos" if stats["avg_r"] >= 0 else "neg")
        + _stat_card("FEES PAID", f"${stats['total_fees']:,.2f}", "neg")
    )

    body = f'<div class="stats-grid">{cards}</div>' "<h2>Equity Curve</h2>" + _equity_sparkline(
        equity
    ) + "<h2>Daily Breakdown</h2>" + daily_table + "<h2>All Trades This Week</h2>" + _trade_table(
        trades, max_rows=500
    )

    label = f"{year}_{week:02d}"
    out_path = _REPORT_DIR / f"weekly_report_{label}.html"
    out_path.write_text(
        _html_page(
            f"Weekly Report – {year} W{week:02d}",
            f"{monday.strftime('%b %d')} – {sunday.strftime('%b %d, %Y')}",
            body,
        ),
        encoding="utf-8",
    )
    log.info(f"Weekly report → {out_path.name}")
    return out_path


def build_full_report() -> Path:
    """
    Build a comprehensive all-time performance report.
    """
    trades = _query("SELECT * FROM trades ORDER BY ts")
    equity = _query("SELECT * FROM equity_curve ORDER BY ts")


    stats = _compute_stats(trades)
    eq_vals = [float(e["equity"]) for e in equity]
    start_eq = eq_vals[0] if eq_vals else 0.0
    end_eq = eq_vals[-1] if eq_vals else 0.0
    total_return_pct = (end_eq - start_eq) / start_eq * 100 if start_eq > 0 else 0.0
    max_dd = _max_drawdown(eq_vals)

    # Top symbols by PnL
    sym_pnl: dict[str, float] = {}
    for t in trades:
        if t.get("pnl") is not None and t["action"] != "BUY":
            sym_pnl[t["symbol"]] = sym_pnl.get(t["symbol"], 0.0) + t["pnl"]
    top_symbols = sorted(sym_pnl.items(), key=lambda x: x[1], reverse=True)[:10]
    sym_rows = "".join(f"<tr><td>{s}</td><td>{_fmt_pnl(p)}</td></tr>" for s, p in top_symbols)
    sym_table = (
        "<table style='max-width:400px'><thead><tr><th>Symbol</th><th>Total PnL</th></tr></thead>"
        f"<tbody>{sym_rows}</tbody></table>"
    )

    # Performance by signal type
    sig_stats: dict[str, dict] = {}
    for t in trades:
        if t.get("pnl") is None or t["action"] == "BUY":
            continue
        sig = t.get("signal_type") or "UNKNOWN"
        if sig not in sig_stats:
            sig_stats[sig] = {"pnl": 0.0, "count": 0, "wins": 0}
        sig_stats[sig]["pnl"] += t["pnl"]
        sig_stats[sig]["count"] += 1
        if t["pnl"] > 0:
            sig_stats[sig]["wins"] += 1

    sig_rows = "".join(
        f"<tr><td>{sig}</td><td>{d['count']}</td>"
        f"<td>{d['wins']/d['count']*100:.1f}%</td>"
        f"<td>{_fmt_pnl(d['pnl'])}</td></tr>"
        for sig, d in sig_stats.items()
    )
    sig_table = (
        "<table style='max-width:500px'><thead>"
        "<tr><th>Signal Type</th><th>Trades</th><th>Win Rate</th><th>Total PnL</th></tr></thead>"
        f"<tbody>{sig_rows}</tbody></table>"
    )

    # Date range
    date_range = "—"
    if trades:
        date_range = f"{trades[0]['ts'][:10]} → {trades[-1]['ts'][:10]}"

    cards = (
        _stat_card("PERIOD", date_range)
        + _stat_card("TOTAL TRADES", str(stats["total_trades"]))
        + _stat_card(
            "NET PnL",
            f"{'+'if stats['net_pnl']>=0 else ''}${stats['net_pnl']:,.2f}",
            "pos" if stats["net_pnl"] >= 0 else "neg",
        )
        + _stat_card(
            "WIN RATE", f"{stats['win_rate']:.1f}%", "pos" if stats["win_rate"] >= 50 else "neg"
        )
        + _stat_card(
            "SHARPE (ann)", f"{stats['sharpe']:.2f}", "pos" if stats["sharpe"] >= 1 else "neg"
        )
        + _stat_card(
            "PROFIT FACTOR",
            f"{stats['profit_factor']:.2f}" if math.isfinite(stats["profit_factor"]) else "∞",
            "pos" if stats["profit_factor"] >= 1.5 else "neg",
        )
        + _stat_card("MAX DRAWDOWN", f"{max_dd:.2f}%", "neg" if max_dd > 10 else "neu")
        + _stat_card(
            "TOTAL RETURN",
            f"{'+'if total_return_pct>=0 else ''}{total_return_pct:.2f}%",
            "pos" if total_return_pct >= 0 else "neg",
        )
        + _stat_card("AVG WIN", f"${stats['avg_win']:,.2f}", "pos")
        + _stat_card("AVG LOSS", f"${stats['avg_loss']:,.2f}", "neg")
        + _stat_card("LARGEST WIN", f"${stats['largest_win']:,.2f}", "pos")
        + _stat_card("LARGEST LOSS", f"${stats['largest_loss']:,.2f}", "neg")
        + _stat_card("TOTAL FEES", f"${stats['total_fees']:,.2f}", "neg")
        + _stat_card("AVG R", f"{stats['avg_r']:+.3f}R", "pos" if stats["avg_r"] >= 0 else "neg")
    )

    body = (
        f'<div class="stats-grid">{cards}</div>'
        "<h2>Equity Curve (All Time)</h2>"
        + _equity_sparkline(equity)
        + "<h2>Top Symbols by PnL</h2>"
        + sym_table
        + "<h2>Performance by Signal Type</h2>"
        + sig_table
        + "<h2>All Trades</h2>"
        + _trade_table(trades, max_rows=1000)
    )

    out_path = _REPORT_DIR / "full_report.html"
    out_path.write_text(
        _html_page("Full Performance Report", "All-time statistics", body),
        encoding="utf-8",
    )
    log.info(f"Full report → {out_path.name}")
    return out_path


def export_csv(out_dir: Path | None = None) -> list[Path]:
    """Export raw tables to CSV for spreadsheet analysis."""
    out_dir = out_dir or _REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = _connect()
    tables = ["trades", "performance", "equity_curve", "signals"]
    written: list[Path] = []
    ts_suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    for table in tables:
        try:
            cur = conn.execute(f"SELECT * FROM {table}")
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            out_file = out_dir / f"{table}_{ts_suffix}.csv"
            with out_file.open("w", encoding="utf-8") as f:
                f.write(",".join(cols) + "\n")
                for row in rows:
                    line = ",".join("" if v is None else str(v).replace(",", ";") for v in row)
                    f.write(line + "\n")
            log.info(f"CSV: {table} ({len(rows)} rows) → {out_file.name}")
            written.append(out_file)
        except sqlite3.OperationalError as exc:
            log.warning(f"Skipping {table}: {exc}")

    conn.close()
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AEGIS PRO report generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--daily", action="store_true", help="Generate today's daily report")
    p.add_argument("--date", type=str, help="Date for daily report (YYYY-MM-DD)")
    p.add_argument("--weekly", action="store_true", help="Generate this week's weekly report")
    p.add_argument("--week", type=int, help="ISO week number (use with --year)")
    p.add_argument("--year", type=int, help="Year for --week")
    p.add_argument("--full", action="store_true", help="Generate full all-time report")
    p.add_argument("--csv", action="store_true", help="Export raw CSV files")
    p.add_argument("--all", action="store_true", help="Generate all report types")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)

    generated: list[Path] = []

    if args.all or args.daily:
        generated.append(build_daily_report(args.date))

    if args.all or args.weekly:
        generated.append(build_weekly_report(args.year, args.week))

    if args.all or args.full:
        generated.append(build_full_report())

    if args.all or args.csv:
        generated.extend(export_csv())

    if not generated:
        # Default: full report
        generated.append(build_full_report())

    print(f"\n✓ Generated {len(generated)} file(s):")
    for p in generated:
        print(f"  {p}")


if __name__ == "__main__":
    main()
