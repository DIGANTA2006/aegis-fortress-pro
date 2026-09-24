# AEGIS PRO – Reports

This directory stores generated performance reports and CSV exports.

## Usage

```bash
# Today's daily report
python reports/report_generator.py --daily

# Specific date
python reports/report_generator.py --daily --date 2024-01-15

# This week's summary
python reports/report_generator.py --weekly

# Specific week
python reports/report_generator.py --weekly --year 2024 --week 3

# All-time full report
python reports/report_generator.py --full

# Raw CSV export for Excel / analysis
python reports/report_generator.py --csv

# Everything at once
python reports/report_generator.py --all
```

## Output Files

| File pattern | Description |
|---|---|
| `daily_report_YYYYMMDD.html` | Day's PnL, trades, equity chart |
| `weekly_report_YYYY_WNN.html` | Weekly summary, Sharpe, drawdown |
| `full_report.html` | All-time stats, top symbols, signal breakdown |
| `trades_TIMESTAMP.csv` | Raw trade journal |
| `performance_TIMESTAMP.csv` | Daily performance records |
| `equity_TIMESTAMP.csv` | Equity curve |
| `signals_TIMESTAMP.csv` | Signal log |
