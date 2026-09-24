import os
import sqlite3
from pathlib import Path


def load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def money(value):
    try:
        return f"{float(value):.8f}"
    except Exception:
        return str(value)


load_dotenv()

db_path = os.environ.get("AEGIS_DATABASE_PATH", "data/aegis_low_capital.db")
print(f"DB: {db_path}")

if not Path(db_path).exists():
    print("Database not found yet. Start the bot first.")
    raise SystemExit(0)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

trades = conn.execute("""
    SELECT *
    FROM trades
    ORDER BY id ASC
""").fetchall()

reports = conn.execute("""
    SELECT *
    FROM execution_reports
    ORDER BY id ASC
""").fetchall()

sell_trades = [row for row in trades if str(row["side"]).upper() == "SELL"]
buy_trades = [row for row in trades if str(row["side"]).upper() == "BUY"]

realized_pnl = sum(float(row["pnl"] or 0.0) for row in sell_trades)
wins = sum(1 for row in sell_trades if float(row["pnl"] or 0.0) > 0)
losses = sum(1 for row in sell_trades if float(row["pnl"] or 0.0) < 0)
flat = len(sell_trades) - wins - losses
win_rate = (wins / len(sell_trades) * 100.0) if sell_trades else 0.0

print("\n=== AEGIS TRADE REPORT ===")
print(f"Execution reports : {len(reports)}")
print(f"Buy trades        : {len(buy_trades)}")
print(f"Completed exits   : {len(sell_trades)}")
print(f"Wins              : {wins}")
print(f"Losses            : {losses}")
print(f"Flat exits        : {flat}")
print(f"Win rate          : {win_rate:.2f}%")
print(f"Realized PnL      : {money(realized_pnl)} USDT")

print("\nRecent trades:")
for row in reversed(trades[-10:]):
    print(
        f"#{row['id']} {row['timestamp']} "
        f"{row['side']} {row['symbol']} "
        f"qty={money(row['quantity'])} "
        f"price={money(row['price'])} "
        f"pnl={money(row['pnl'])}"
    )

conn.close()
