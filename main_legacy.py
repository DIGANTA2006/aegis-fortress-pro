from core.production_env_check import check_production_env
from core.graceful_shutdown import register_signals
from core.logging_config import setup_logging
"""
main.py  â€“  AEGIS PRO v2
Entry point.  All wiring between modules lives here.

Start with:
    python main.py              # paper trading (default)
    python main.py --backtest   # run backtests then exit

Environment variables (minimum required for LIVE):
    BINANCE_API_KEY, BINANCE_SECRET, TG_TOKEN, TG_CHAT_ID
    AEGIS_MODE=LIVE
    AEGIS_LIVE_CONFIRM=YES_I_ACCEPT_THE_RISK
    AEGIS_CONFIG_PASSWORD=<strong_password>
"""

import argparse
import gc
import logging
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Our modules
# ---------------------------------------------------------------------------
from config import PATHS, AegisConfig, load_config, validate_config
from db import TickDB, TradeDB
from exchange import ExchangeManager
from execution import ExecutionEngine
from market_data import FeatureEngine, fetch_ohlcv, validate_signal_conditions
from models import PairsSignalModel, SignalFusion, XGBSignalModel
from monitor import TelegramNotifier, start_dashboard, update_dashboard_state
from risk import RiskManager, Trade
from utils import atomic_write_json, format_usdt, now_iso, safe_read_json, setup_logger
from watchdog import Watchdog

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log = setup_logger("aegis.main", log_path=PATHS["log"], level=logging.INFO)


# ---------------------------------------------------------------------------
# Trading bot
# ---------------------------------------------------------------------------


class AegisPro:
    """
    Main orchestrator.  Owns the trading loop and coordinates all subsystems.
    """

    DAILY_RESET_HOUR = 0  # UTC midnight
    WEEKLY_RESET_DOW = 0  # Monday

    def __init__(self, cfg: AegisConfig):
        self.cfg = cfg
        self.running = True

        # ---- Core subsystems ----
        log.info(f"Initialising AEGIS PRO v2  mode={cfg.mode}")
        self.exchange_mgr = ExchangeManager(cfg)
        self.primary_ex = self.exchange_mgr.primary
        self.risk = RiskManager(cfg)
        self.db = TradeDB()
        self.tick_db = TickDB()
        self.fe = FeatureEngine(cfg)
        self.ml = XGBSignalModel(cfg)
        self.pairs_model = PairsSignalModel(cfg)
        self.fusion = SignalFusion(cfg)
        self.telegram = TelegramNotifier(cfg.tg_token, cfg.tg_chat_id)
        self.watchdog = Watchdog(cfg)
        self.execution = ExecutionEngine(self.primary_ex, cfg, self.risk)

        # ---- State ----
        self.active_trades: Dict[str, Trade] = {}
        self.paper_balance: float = 10_000.0  # USDT
        self.daily_pnl: float = 0.0
        self.cooldowns: Dict[str, float] = {}

        # ---- Timestamps ----
        self._last_ml_train = 0.0
        self._last_corr_update = 0.0
        self._last_daily_reset: str = ""  # ISO date string e.g. "2024-01-15"
        self._last_weekly_reset = 0.0
        self._last_backup = 0.0
        self._last_pair_update = 0.0

        # ---- SIGTERM / SIGINT handling ----
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        # ---- Load persisted state ----
        self._load_state()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def equity(self) -> float:
        """Total equity = free balance + unrealised PnL of open positions."""
        base = self._get_base_balance()
        unrealised = sum(
            (self._last_price(sym) - t.entry_price) * t.qty
            for _sym, t in self.active_trades.items()
        )
        return base + unrealised

    def _get_base_balance(self) -> float:
        if self.cfg.mode == "PAPER":
            return self.paper_balance
        usdt = self.exchange_mgr.get_total_usdt_balance()
        return usdt if usdt > 0 else self.paper_balance

    def _last_price(self, symbol: str) -> float:
        try:
            return float(self.primary_ex.fetch_ticker(symbol).get("last", 0))
        except Exception:
            return 0.0

    def _open_risk(self) -> float:
        total = 0.0
        for _sym, t in self.active_trades.items():
            risk = (t.entry_price - t.stop_loss) * t.qty
            if risk > 0:
                total += risk
        return total

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        log.info("Starting AEGIS PRO trading loop.")
        self.telegram.system_info(
            f"ðŸš€ AEGIS PRO started  mode={self.cfg.mode}  " f"symbols={len(self.cfg.watchlist)}"
        )
        self.watchdog.start()
        start_dashboard(self.cfg)

        # Reconcile orphaned orders on startup
        self.exchange_mgr.reconcile_all_open_orders(self.cfg.watchlist)

        # Initial ML load
        self.ml.load()

        while self.running:
            loop_start = time.time()
            try:
                self._tick()
            except Exception as exc:
                log.exception(f"Unhandled exception in main loop: {exc}")
                self.telegram.error_alert("main_loop", str(exc))

            # Beat the watchdog
            self.watchdog.beat()

            # Maintain scan interval
            elapsed = time.time() - loop_start
            sleep_for = max(0, self.cfg.scan_interval_secs - elapsed)
            log.debug(f"Loop took {elapsed:.1f}s. Sleeping {sleep_for:.1f}s.")
            time.sleep(sleep_for)

    # ------------------------------------------------------------------

    def _tick(self) -> None:
        """One full scan cycle."""
        now = time.time()
        self.risk.bar_counter += 1
        current_equity = self.equity

        # ---- Periodic resets ----
        self._maybe_daily_reset(current_equity)
        self._maybe_weekly_reset(current_equity)

        # ---- Update equity peaks ----
        self.risk.update_equity_peaks(current_equity)
        self.db.log_equity(current_equity)

        # ---- ML retrain ----
        if now - self._last_ml_train > self.cfg.ml_retrain_interval_secs:
            self._retrain_ml()
            self._last_ml_train = now

        # ---- Pairs cointegration update ----
        if now - self._last_pair_update > self.cfg.correlation_update_secs:
            threading.Thread(target=self._update_pairs, daemon=True, name="pairs-update").start()
            self._last_pair_update = now

        # ---- Signal fusion weight update ----
        self.fusion.update_weights()

        # ---- Halt check ----
        halted, halt_reason = self.risk.is_trading_halted(current_equity)
        if halted:
            log.warning(f"Trading halted: {halt_reason}")
            self._manage_open_positions(current_equity)
            self._push_dashboard(current_equity, halted=True)
            return

        # ---- Manage existing positions ----
        self._manage_open_positions(current_equity)

        # ---- Look for new entries ----
        if (
            len(self.active_trades) < self.cfg.max_concurrent_trades
            and self.risk.trades_today < self.cfg.max_daily_trades
        ):
            self._scan_for_entries(current_equity)

        # ---- Backup ----
        if now - self._last_backup > 86400:
            self.db.backup(Path(PATHS["backups"]))
            self._last_backup = now

        # ---- Persist state ----
        self._save_state()

        # ---- Dashboard update ----
        self._push_dashboard(current_equity)

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def _manage_open_positions(self, equity: float) -> None:
        to_close: List[str] = []

        for symbol, trade in list(self.active_trades.items()):
            try:
                price = self._last_price(symbol)
                if price <= 0:
                    continue

                # Fetch current ATR for trailing
                df = fetch_ohlcv(self.primary_ex, symbol, "15m", limit=50)
                current_atr = trade.atr_entry
                if df is not None and "atr" in df.columns:
                    current_atr = float(df["atr"].iloc[-2])
                    trade.current_atr = current_atr

                action = self._check_trade_exits(trade, price, symbol)
                if action:
                    to_close.append((symbol, action, price))
            except Exception as exc:
                log.error(f"Position management error {symbol}: {exc}")

        for symbol, action, price in to_close:
            self._close_trade(symbol, action, price)

    def _check_trade_exits(self, trade: Trade, price: float, symbol: str) -> Optional[str]:
        atr = trade.current_atr

        # ---- Hard stop ----
        if price <= trade.stop_loss:
            return "STOP_LOSS"

        # ---- TP1 partial exit ----
        if not trade.tp1_taken and price >= trade.tp1:
            sell_qty = trade.qty * self.cfg.atr_tp1_frac
            filled = self._partial_close(symbol, trade, sell_qty, price, "TP1")
            if filled:
                # Only mark taken AFTER confirmed fill
                trade.tp1_taken = True
                # Move stop to breakeven
                trade.stop_loss = max(trade.stop_loss, trade.entry_price * 1.001)
                trade.trail_activated = True

        # ---- TP2 partial exit ----
        if trade.tp1_taken and not trade.tp2_taken and price >= trade.tp2:
            sell_qty = trade.qty * self.cfg.atr_tp2_frac
            filled = self._partial_close(symbol, trade, sell_qty, price, "TP2")
            if filled:
                trade.tp2_taken = True

        # ---- Early trail to breakeven ----
        profit_in_atr = (price - trade.entry_price) / max(trade.atr_entry, 1e-10)
        if not trade.early_trail and profit_in_atr >= self.cfg.early_trail_trigger:
            trade.early_trail = True
            new_stop = trade.entry_price + 0.001 * trade.entry_price
            trade.stop_loss = max(trade.stop_loss, new_stop)

        # ---- Chandelier trailing stop ----
        if trade.trail_activated:
            trail_stop = price - 2.0 * atr
            trade.stop_loss = max(trade.stop_loss, trail_stop)

        # ---- Time-based stop ----
        if self.risk.should_time_stop(trade):
            unrealised = (price - trade.entry_price) * trade.qty
            if unrealised <= 0:
                return "TIME_STOP"

        return None

    def _partial_close(
        self, symbol: str, trade: Trade, qty: float, price: float, reason: str
    ) -> bool:
        """Execute a partial close. Returns True on successful fill, False otherwise."""
        if qty <= 0 or trade.qty <= 0:
            return False
        qty = min(qty, trade.qty)
        result = self.execution.execute_sell(symbol, qty, price, reason=reason)
        if result:
            fill_price = float(result.get("average", price))
            pnl = (fill_price - trade.entry_price) * qty - float(
                result.get("fee", {}).get("cost", 0)
            )
            trade.qty -= qty
            if self.cfg.mode == "PAPER":
                self.paper_balance += fill_price * qty
            self.daily_pnl += pnl
            self.db.log_trade(
                action=reason,
                symbol=symbol,
                price=fill_price,
                qty=qty,
                pnl=pnl,
                signal_type=trade.signal_type,
                mode=self.cfg.mode,
            )
            log.info(f"Partial {reason}: {symbol} qty={qty:.6g} @ {fill_price:.6g} pnl=${pnl:+.2f}")
            return True
        else:
            log.warning(f"Partial {reason} failed for {symbol}. Will retry next tick.")
            return False

    def _close_trade(self, symbol: str, reason: str, price: float) -> None:
        trade = self.active_trades.get(symbol)
        if not trade:
            return

        # Retry loop for critical exits (stops must always fill)
        result = None
        for attempt in range(3):
            result = self.execution.execute_sell(symbol, trade.qty, price, reason=reason)
            if result:
                break
            log.warning(f"Sell attempt {attempt+1}/3 failed for {symbol}. Retrying...")
            time.sleep(2)

        if not result:
            log.critical(f"FAILED to close {symbol} after 3 attempts! Manual intervention needed.")
            self.telegram.error_alert("EXIT_FAILED", f"{symbol} {reason} @{price:.4g}")
            return

        fill_price = float(result.get("average", price))
        fee = float(result.get("fee", {}).get("cost", 0))
        pnl = (fill_price - trade.entry_price) * trade.qty - trade.entry_fee - fee
        r_multiple = pnl / max(trade.risk_dollars, 1e-6)

        # Update balance
        if self.cfg.mode == "PAPER":
            self.paper_balance += fill_price * trade.qty
        self.daily_pnl += pnl

        # Update risk manager
        if pnl > 0:
            self.risk.on_win()
        else:
            self.risk.on_loss()
        self.risk.update_stats(pnl, r_multiple)

        # Record slippage
        self.risk.record_slippage(symbol, price, fill_price)

        # Attribute to model
        self.fusion.record_trade_pnl("technical" if trade.signal_type else "ml", pnl)

        # Cooldown on loss
        if pnl < 0:
            self.cooldowns[symbol] = time.time() + self.cfg.symbol_cooldown_secs

        # DB + telegram
        self.db.log_trade(
            action=reason,
            symbol=symbol,
            price=fill_price,
            qty=trade.qty,
            pnl=pnl,
            r_multiple=r_multiple,
            fees=fee,
            signal_type=trade.signal_type,
            mode=self.cfg.mode,
        )
        self.telegram.trade_exit(symbol, fill_price, trade.qty, pnl, reason, self.cfg.mode)

        log.info(
            f"CLOSED {symbol}: {reason} @ {fill_price:.6g} " f"pnl=${pnl:+.2f} R={r_multiple:+.2f}"
        )
        del self.active_trades[symbol]

    # ------------------------------------------------------------------
    # Entry scanning
    # ------------------------------------------------------------------

    def _scan_for_entries(self, equity: float) -> None:
        # BTC macro filter
        btc_bullish = self._is_btc_bullish()

        for symbol in self.cfg.watchlist:
            if not self.running:
                break
            if symbol in self.active_trades:
                continue
            if self.risk.is_blacklisted(symbol):
                continue
            if time.time() < self.cooldowns.get(symbol, 0):
                continue
            if len(self.active_trades) >= self.cfg.max_concurrent_trades:
                break

            try:
                self._evaluate_symbol(symbol, equity, btc_bullish)
            except Exception as exc:
                log.error(f"Entry eval error {symbol}: {exc}")

    def _evaluate_symbol(self, symbol: str, equity: float, btc_bullish: bool) -> None:
        # Fetch multi-TF data
        df_15m = fetch_ohlcv(self.primary_ex, symbol, "15m")
        df_1h = fetch_ohlcv(self.primary_ex, symbol, "1h")
        df_4h = fetch_ohlcv(self.primary_ex, symbol, "4h")

        if df_15m is None or len(df_15m) < 210:
            return

        # Fetch order book for OB features
        ob = None
        try:
            ob = self.primary_ex.fetch_order_book(symbol, limit=20)
        except Exception:
            pass

        # Compute features
        row = self.fe.compute(df_15m, df_1h=df_1h, df_4h=df_4h, ob=ob)
        if row is None:
            return

        # Technical signal
        sig = validate_signal_conditions(row, self.cfg, btc_bullish, symbol)

        # ML probability
        ml_prob = self.ml.predict(row)

        # OB imbalance
        ob_imb = float(row.get("ob_imbalance", 1.0))
        if ob_imb != ob_imb:  # nan check
            ob_imb = 1.0

        # Pairs z-score (optional boost)
        pairs_z = None
        # (pairs model runs asynchronously; query its cache)
        # For now we leave it as None unless specific pairs signal detected

        # Fused probability
        fused = self.fusion.fuse(sig, ml_prob, ob_imb, pairs_z)

        # Log signal
        action = "TRADE" if (sig and fused >= self.cfg.fused_threshold) else "SKIP"
        self.db.log_signal(symbol, sig, ml_prob, ob_imb, fused, action)

        if not sig or fused < self.cfg.fused_threshold:
            return

        # Sizing
        current_price = float(row.get("c", 0))
        atr = float(row.get("atr", current_price * 0.01))

        sizing = self.risk.calculate_position_size(
            price=current_price,
            atr=atr,
            equity=equity,
            open_risk=self._open_risk(),
            ml_prob=ml_prob,
        )
        if sizing is None:
            return

        # Execute
        result = self.execution.execute_buy(symbol, sizing["amount"], current_price)
        if not result:
            return

        fill_price = float(result.get("average", current_price))
        qty = float(result.get("filled", sizing["amount"]))
        fee = float(result.get("fee", {}).get("cost", 0))

        if self.cfg.mode == "PAPER":
            self.paper_balance -= fill_price * qty

        # Register trade
        trade = Trade(
            symbol=symbol,
            entry_price=fill_price,
            qty=qty,
            initial_qty=qty,
            stop_loss=sizing["stop_price"],
            tp1=sizing["tp1_price"],
            tp2=sizing["tp2_price"],
            atr_entry=atr,
            current_atr=atr,
            risk_dollars=sizing["risk_dollars"],
            entry_fee=fee,
            signal_type=sig,
            entry_bar_index=self.risk.bar_counter,
            mode=self.cfg.mode,
        )
        self.active_trades[symbol] = trade
        self.risk.trades_today += 1

        self.db.log_trade(
            action="BUY",
            symbol=symbol,
            price=fill_price,
            qty=qty,
            fees=fee,
            signal_type=sig,
            ml_prob=ml_prob,
            fused_prob=fused,
            mode=self.cfg.mode,
        )
        self.telegram.trade_entry(symbol, fill_price, qty, sig, self.cfg.mode)

        log.info(
            f"ENTRY {symbol}: {sig} @ {fill_price:.6g} "
            f"qty={qty:.6g} stop={sizing['stop_price']:.6g} "
            f"tp1={sizing['tp1_price']:.6g} fused={fused:.3f}"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_btc_bullish(self) -> bool:
        """Simple macro filter: BTC must be above SMA-200 to take altcoin longs."""
        try:
            df = fetch_ohlcv(self.primary_ex, "BTC/USDT", "1d", limit=220)
            if df is None or len(df) < 50:
                return True  # can't determine â†’ allow
            sma200 = df["c"].rolling(200, min_periods=50).mean().iloc[-1]
            last = float(df["c"].iloc[-1])
            return last > sma200
        except Exception:
            return True

    def _retrain_ml(self) -> None:
        log.info("Starting ML retrain (background thread)...")

        def _do():
            frames = {}
            for symbol in self.cfg.watchlist[:10]:  # limit for speed
                df = fetch_ohlcv(self.primary_ex, symbol, "15m", limit=2000)
                if df is not None:
                    df_feat = df.copy()
                    self.fe._add_classical(df_feat)
                    self.fe._add_macd(df_feat)
                    self.fe._add_ichimoku(df_feat)
                    self.fe._add_microstructure(df_feat)
                    frames[symbol] = df_feat
            self.ml.train(frames)

        threading.Thread(target=_do, daemon=True, name="ml-retrain").start()

    def _update_pairs(self) -> None:
        price_series = {}
        for symbol in self.cfg.watchlist:
            df = fetch_ohlcv(self.primary_ex, symbol, "1d", limit=90)
            if df is not None:
                price_series[symbol] = df["c"]
        self.pairs_model.update_cointegration(price_series)

    # ------------------------------------------------------------------
    # Daily / weekly resets
    # ------------------------------------------------------------------

    def _maybe_daily_reset(self, equity: float) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        if today == self._last_daily_reset:
            return
        self._last_daily_reset = today

        # Log yesterday's performance
        if self.risk.total_trades > 0:
            self.db.update_performance(
                date=today,
                trades=self.risk.trades_today,
                wins=self.risk.wins,
                losses=self.risk.losses,
                pnl=self.daily_pnl,
                win_rate=self.risk.win_rate,
                expectancy=self.risk.expectancy,
            )
            self.telegram.daily_summary(
                self.risk.trades_today, self.risk.wins, self.risk.losses, self.daily_pnl, equity
            )

        self.risk.reset_daily(equity)
        self.daily_pnl = 0.0
        log.info(f"Daily reset complete. Equity={format_usdt(equity)}")

    def _maybe_weekly_reset(self, equity: float) -> None:
        dow = datetime.now(timezone.utc).weekday()
        week_key = f"{datetime.now(timezone.utc).isocalendar()[1]}"
        if week_key == getattr(self, "_last_weekly_key", None):
            return
        if dow != self.WEEKLY_RESET_DOW:
            return
        self._last_weekly_key = week_key
        self.risk.reset_weekly(equity)
        log.info("Weekly reset complete.")

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        state = {
            "paper_balance": self.paper_balance,
            "daily_pnl": self.daily_pnl,
            "peak_equity": self.risk.historical_peak,
            "total_trades": self.risk.total_trades,
            "total_wins": self.risk.total_wins,
            "total_losses": self.risk.total_losses,
            "avg_win_r": self.risk.avg_win_r,
            "avg_loss_r": self.risk.avg_loss_r,
            "win_rate": self.risk.win_rate,
            "cooldowns": {k: v for k, v in self.cooldowns.items()},
            "active_trades": {
                sym: {
                    "entry_price": t.entry_price,
                    "qty": t.qty,
                    "initial_qty": t.initial_qty,
                    "stop_loss": t.stop_loss,
                    "tp1": t.tp1,
                    "tp2": t.tp2,
                    "atr_entry": t.atr_entry,
                    "current_atr": t.current_atr,
                    "risk_dollars": t.risk_dollars,
                    "entry_fee": t.entry_fee,
                    "signal_type": t.signal_type,
                    "entry_time": t.entry_time,
                    "entry_bar_index": t.entry_bar_index,
                    "tp1_taken": t.tp1_taken,
                    "tp2_taken": t.tp2_taken,
                    "trail_activated": t.trail_activated,
                    "early_trail": t.early_trail,
                    "mode": t.mode,
                }
                for _sym, t in self.active_trades.items()
            },
            "saved_at": now_iso(),
        }
        atomic_write_json(Path(PATHS["positions"]), state)

    def _load_state(self) -> None:
        data = safe_read_json(Path(PATHS["positions"]), default={})
        if not data:
            return
        self.paper_balance = float(data.get("paper_balance", 10_000.0))
        self.daily_pnl = float(data.get("daily_pnl", 0.0))
        self.risk.historical_peak = float(data.get("peak_equity", 0.0))
        self.risk.total_trades = int(data.get("total_trades", 0))
        self.risk.total_wins = int(data.get("total_wins", 0))
        self.risk.total_losses = int(data.get("total_losses", 0))
        self.risk.avg_win_r = float(data.get("avg_win_r", 0.0))
        self.risk.avg_loss_r = float(data.get("avg_loss_r", 0.0))
        self.risk.win_rate = float(data.get("win_rate", 0.0))
        self.cooldowns = {k: float(v) for k, v in data.get("cooldowns", {}).items()}

        for sym, td in data.get("active_trades", {}).items():
            try:
                self.active_trades[sym] = Trade(
                    symbol=sym,
                    entry_price=float(td["entry_price"]),
                    qty=float(td["qty"]),
                    initial_qty=float(td["initial_qty"]),
                    stop_loss=float(td["stop_loss"]),
                    tp1=float(td["tp1"]),
                    tp2=float(td["tp2"]),
                    atr_entry=float(td["atr_entry"]),
                    current_atr=float(td.get("current_atr", td["atr_entry"])),
                    risk_dollars=float(td["risk_dollars"]),
                    entry_fee=float(td.get("entry_fee", 0)),
                    signal_type=td.get("signal_type", ""),
                    entry_time=float(td.get("entry_time", time.time())),
                    entry_bar_index=int(td.get("entry_bar_index", 0)),
                    tp1_taken=bool(td.get("tp1_taken", False)),
                    tp2_taken=bool(td.get("tp2_taken", False)),
                    trail_activated=bool(td.get("trail_activated", False)),
                    early_trail=bool(td.get("early_trail", False)),
                    mode=td.get("mode", self.cfg.mode),
                )
            except Exception as exc:
                log.error(f"Could not restore trade {sym}: {exc}")

        # Ensure daily/weekly equity baselines are set after reload
        # so circuit-breaker loss checks work correctly from the first tick.
        if self.risk.daily_start_equity <= 0:
            self.risk.daily_start_equity = (
                self.paper_balance or self.risk.historical_peak or 10_000.0
            )
        if self.risk.weekly_start_equity <= 0:
            self.risk.weekly_start_equity = self.risk.daily_start_equity

        log.info(
            f"State loaded: {len(self.active_trades)} open positions, "
            f"balance={format_usdt(self.paper_balance)}"
        )

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    def _push_dashboard(self, equity: float, halted: bool = False) -> None:
        positions_data = {}
        for _sym, t in self.active_trades.items():
            p = self._last_price(sym)
            positions_data[sym] = {
                "entry_price": t.entry_price,
                "current_price": p,
                "qty": t.qty,
                "stop_loss": t.stop_loss,
                "tp1": t.tp1,
                "tp2": t.tp2,
                "unrealised_pnl": (p - t.entry_price) * t.qty,
            }
        update_dashboard_state(
            status="HALTED" if halted else "ONLINE",
            equity=equity,
            positions=positions_data,
            daily_pnl=self.daily_pnl,
            total_trades=self.risk.trades_today,
            win_rate=self.risk.win_rate,
        )

    # ------------------------------------------------------------------
    # Signal handler / shutdown
    # ------------------------------------------------------------------

    def _handle_signal(self, signum, frame) -> None:
        log.info(f"Signal {signum} received. Initiating graceful shutdown.")
        self.running = False

    def shutdown(self) -> None:
        log.info("Shutting down AEGIS PRO...")
        self.watchdog.stop()
        self._save_state()
        self.telegram.daily_summary(
            self.risk.trades_today, self.risk.wins, self.risk.losses, self.daily_pnl, self.equity
        )
        self.telegram.system_info("ðŸ›‘ AEGIS PRO shut down gracefully.")
        self.telegram.flush_all()
        gc.collect()
        log.info("Shutdown complete.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AEGIS PRO v2 Crypto Trading Bot")
    p.add_argument("--backtest", action="store_true", help="Run backtests and exit")
    p.add_argument(
        "--config-password", type=str, default=None, help="Password for encrypted config file"
    )
    p.add_argument("--validate-config", action="store_true", help="Validate config and exit")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    setup_logging(log_file=str(PATHS["log"]))
    register_signals()

    cfg = load_config(password=args.config_password)
    if cfg.mode == "LIVE":
        check_production_env()

    errors = validate_config(cfg)
    if errors:
        for e in errors:
            log.critical(f"Config error: {e}")
        if args.validate_config:
            sys.exit(1)
        if cfg.mode == "LIVE":
            sys.exit(1)
        log.warning("Continuing with config errors in PAPER mode.")

    if args.validate_config:
        log.info("Config is valid.")
        sys.exit(0)

    if args.backtest:
        _run_backtest_mode(cfg)
        return

    # Live / paper trading
    bot = AegisPro(cfg)
    try:
        bot.run()
    finally:
        bot.shutdown()


def _run_backtest_mode(cfg: AegisConfig) -> None:
    from backtest import run_batch_backtest
    from exchange import ExchangeManager
    from models import SignalFusion, XGBSignalModel

    log.info("=== BACKTEST MODE ===")
    try:
        ex_mgr = ExchangeManager(cfg)
        primary = ex_mgr.primary
    except Exception as exc:
        log.critical(f"Exchange init failed: {exc}")
        sys.exit(1)

    ml = XGBSignalModel(cfg)
    ml.load()
    fusion = SignalFusion(cfg)

    ohlcv_data = {}
    for sym in cfg.watchlist[:5]:  # limit for demo
        df = fetch_ohlcv(primary, sym, "15m", limit=2000)
        if df is not None:
            ohlcv_data[sym] = df
            log.info(f"Loaded {len(df)} bars for {sym}")

    results = run_batch_backtest(cfg, ohlcv_data, ml, fusion)

    # Print summary table
    print("\n" + "=" * 60)
    for _sym, r in results.items():
        print(r.summary())


if __name__ == "__main__":
    
    setup_logging(log_file=str(PATHS["log"]))
    register_signals()

    if cfg.mode == "LIVE":
        check_production_env()

    
    setup_logging(log_file=str(PATHS["log"]))
    register_signals()

    if cfg.mode == "LIVE":
        check_production_env()

    
setup_logging(log_file=str(PATHS["log"]))
register_signals()

if cfg.mode == "LIVE":
    check_production_env()


setup_logging(log_file=str(PATHS["log"]))
register_signals()

if cfg.mode == "LIVE":
    check_production_env()

main()




