from pathlib import Path

strategy_path = Path("strategies/mean_reversion_imbalance.py")
text = strategy_path.read_text(encoding="utf-8", errors="replace")

if "self.taker_fee_bps = self._float_env" not in text:
    text = text.replace(
'''        self.bad_symbol_drop_bps = bad_symbol_drop_bps

        self._mid_history: dict[str, deque[float]] = {}
''',
'''        self.bad_symbol_drop_bps = bad_symbol_drop_bps

        # Phase 3A hardening knobs. Defaults preserve old test behaviour;
        # production values are enabled through .env.
        self.taker_fee_bps = self._float_env("AEGIS_STRATEGY_TAKER_FEE_BPS", 0.0)
        self.slippage_bps = self._float_env("AEGIS_STRATEGY_SLIPPAGE_BPS", 0.0)
        self.expected_edge_multiplier = self._float_env(
            "AEGIS_STRATEGY_EXPECTED_EDGE_MULTIPLIER", 1.0
        )
        self.round_trip_cost_bps = max(
            0.0,
            (self.taker_fee_bps * 2.0) + self.slippage_bps,
        )
        self.required_min_profit_bps = max(
            self.min_profit_after_fee_bps,
            self.round_trip_cost_bps + self._float_env(
                "AEGIS_STRATEGY_PROFIT_BUFFER_BPS", 0.0
            ),
        )
        self.required_expected_edge_bps = max(
            self.required_min_profit_bps,
            self.round_trip_cost_bps * self.expected_edge_multiplier,
        )

        self.imbalance_confirm_snapshots = max(
            1,
            self._int_env("AEGIS_STRATEGY_IMBALANCE_CONFIRM_SNAPSHOTS", 1),
        )
        self.dynamic_stop_enabled = self._bool_env(
            "AEGIS_STRATEGY_DYNAMIC_STOP_ENABLED", False
        )
        self.dynamic_stop_min_bps = self._float_env(
            "AEGIS_STRATEGY_DYNAMIC_STOP_MIN_BPS", self.stop_loss_bps
        )
        self.dynamic_stop_max_bps = self._float_env(
            "AEGIS_STRATEGY_DYNAMIC_STOP_MAX_BPS", self.stop_loss_bps
        )
        self.dynamic_stop_multiplier = self._float_env(
            "AEGIS_STRATEGY_DYNAMIC_STOP_MULTIPLIER", 1.5
        )
        self.dynamic_stop_lookback = max(
            5,
            self._int_env("AEGIS_STRATEGY_DYNAMIC_STOP_LOOKBACK", 20),
        )

        self.btc_filter_enabled = self._bool_env("AEGIS_BTC_FILTER_ENABLED", False)
        self.btc_filter_require_data = self._bool_env(
            "AEGIS_BTC_FILTER_REQUIRE_DATA", False
        )
        self.btc_symbol = os.getenv("AEGIS_BTC_FILTER_SYMBOL", "BTC/USDT").strip() or "BTC/USDT"
        self.trade_btc_symbol = self._bool_env("AEGIS_TRADE_BTC_SYMBOL", True)
        self.btc_min_observations = max(
            5,
            self._int_env("AEGIS_BTC_FILTER_MIN_OBSERVATIONS", 10),
        )
        self.btc_danger_drop_bps = self._float_env(
            "AEGIS_BTC_FILTER_DANGER_DROP_BPS", 40.0
        )
        self.btc_volatility_max_bps = self._float_env(
            "AEGIS_BTC_FILTER_MAX_VOLATILITY_BPS", 80.0
        )

        self._mid_history: dict[str, deque[float]] = {}
'''
    )

    text = text.replace(
'''        self._blocked_until: dict[str, float] = {}

        self.ticks_seen = 0
''',
'''        self._blocked_until: dict[str, float] = {}
        self._imbalance_history: dict[str, deque[float]] = {}

        self.ticks_seen = 0
'''
    )

    text = text.replace(
'''        self.skipped_for_kill_switch = 0
''',
'''        self.skipped_for_kill_switch = 0
        self.skipped_for_btc_filter = 0
        self.skipped_for_edge = 0
        self.skipped_for_imbalance_confirmation = 0
'''
    )

    text = text.replace(
'''        imbalance = float(
            orderbook.get("imbalance", 0.0)
        )

        position = self.ledger.get_position(
''',
'''        imbalance = float(
            orderbook.get("imbalance", 0.0)
        )

        if symbol == self.btc_symbol and not self.trade_btc_symbol:
            # Keep BTC as a market-regime monitor without trading it.
            return []

        position = self.ledger.get_position(
'''
    )

    text = text.replace(
'''            if self._is_entry_on_cooldown(symbol):
                self.skipped_for_cooldown += 1
                return []

            entry_signal = self._build_entry_signal(
                symbol=symbol,
                mid_price=mid_price,
                best_bid=float(orderbook.get("best_bid", 0.0)),
''',
'''            if self._is_entry_on_cooldown(symbol):
                self.skipped_for_cooldown += 1
                return []

            if not self._btc_market_ok():
                self.skipped_for_btc_filter += 1
                return []

            expected_edge_bps = self._expected_edge_bps(
                history,
                mid_price,
            )

            entry_signal = self._build_entry_signal(
                symbol=symbol,
                mid_price=mid_price,
                best_bid=float(orderbook.get("best_bid", 0.0)),
'''
    )

    text = text.replace(
'''                best_ask=float(orderbook.get("best_ask", 0.0)),
                zscore=zscore,
                imbalance=imbalance,
            )
''',
'''                best_ask=float(orderbook.get("best_ask", 0.0)),
                zscore=zscore,
                imbalance=imbalance,
                expected_edge_bps=expected_edge_bps,
            )
''',
        1,
    )

    text = text.replace(
'''        imbalance: float,
    ) -> TradeSignal | None:
''',
'''        imbalance: float,
        expected_edge_bps: float,
    ) -> TradeSignal | None:
'''
    )

    text = text.replace(
'''        if (
            zscore <= -self.entry_zscore
            and imbalance >= self.imbalance_threshold
        ):
            return TradeSignal(
''',
'''        if zscore <= -self.entry_zscore:
            if expected_edge_bps < self.required_expected_edge_bps:
                self.skipped_for_edge += 1
                return None

            if not self._imbalance_confirmed(
                symbol,
                imbalance,
                positive=True,
            ):
                self.skipped_for_imbalance_confirmation += 1
                return None

            if imbalance < self.imbalance_threshold:
                return None

            return TradeSignal(
'''
    )

    text = text.replace(
'''            if pnl_bps >= self.take_profit_bps:
                reason = "take_profit"
            elif pnl_bps <= -self.stop_loss_bps:
                reason = "stop_loss"
            elif (
                zscore >= -self.exit_zscore
                and pnl_bps >= self.min_profit_after_fee_bps
            ):
''',
'''            if pnl_bps >= self._fee_adjusted_take_profit_bps():
                reason = "take_profit"
            elif pnl_bps <= -self._dynamic_stop_loss_bps(history=self._mid_history.get(symbol)):
                reason = "stop_loss"
            elif (
                zscore >= -self.exit_zscore
                and pnl_bps >= self.required_min_profit_bps
            ):
'''
    )

    text = text.replace(
'''            if pnl_bps >= self.take_profit_bps:
                reason = "take_profit"
            elif pnl_bps <= -self.stop_loss_bps:
                reason = "stop_loss"
            elif (
                zscore <= self.exit_zscore
                and pnl_bps >= self.min_profit_after_fee_bps
            ):
''',
'''            if pnl_bps >= self._fee_adjusted_take_profit_bps():
                reason = "take_profit"
            elif pnl_bps <= -self._dynamic_stop_loss_bps(history=self._mid_history.get(symbol)):
                reason = "stop_loss"
            elif (
                zscore <= self.exit_zscore
                and pnl_bps >= self.required_min_profit_bps
            ):
'''
    )

    helper_methods = '''
    def _fee_adjusted_take_profit_bps(self) -> float:
        return max(
            self.take_profit_bps,
            self.round_trip_cost_bps + self.required_min_profit_bps,
        )

    def _dynamic_stop_loss_bps(self, history: deque[float] | None) -> float:
        if not self.dynamic_stop_enabled:
            return self.stop_loss_bps

        volatility_bps = self._volatility_bps(
            history,
            lookback=self.dynamic_stop_lookback,
        )
        raw = volatility_bps * self.dynamic_stop_multiplier
        return max(
            self.dynamic_stop_min_bps,
            min(self.dynamic_stop_max_bps, raw),
        )

    def _expected_edge_bps(self, history: deque[float], mid_price: float) -> float:
        values = list(history)
        if not values or mid_price <= 0:
            return 0.0

        avg = mean(values)
        if avg <= mid_price:
            return 0.0

        return ((avg - mid_price) / mid_price) * 10_000.0

    def _volatility_bps(self, history: deque[float] | None, lookback: int) -> float:
        if history is None:
            return 0.0

        values = list(history)[-max(2, lookback):]
        if len(values) < 2:
            return 0.0

        avg = mean(values)
        if avg <= 0:
            return 0.0

        return (pstdev(values) / avg) * 10_000.0

    def _imbalance_confirmed(
        self,
        symbol: str,
        imbalance: float,
        *,
        positive: bool,
    ) -> bool:
        history = self._imbalance_history.setdefault(
            symbol,
            deque(maxlen=self.imbalance_confirm_snapshots),
        )
        history.append(imbalance)

        if len(history) < self.imbalance_confirm_snapshots:
            return False

        if positive:
            return all(value >= self.imbalance_threshold for value in history)

        return all(value <= -self.imbalance_threshold for value in history)

    def _btc_market_ok(self) -> bool:
        if not self.btc_filter_enabled:
            return True

        history = self._mid_history.get(self.btc_symbol)
        if history is None or len(history) < self.btc_min_observations:
            return not self.btc_filter_require_data

        recent_return = self._recent_return_bps(history)
        if recent_return <= -abs(self.btc_danger_drop_bps):
            return False

        volatility = self._volatility_bps(
            history,
            lookback=self.btc_min_observations,
        )
        if volatility >= self.btc_volatility_max_bps:
            return False

        return True

    def _bool_env(self, name: str, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "y", "on"}

    def _float_env(self, name: str, default: float) -> float:
        raw = os.getenv(name)
        if raw is None or not str(raw).strip():
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    def _int_env(self, name: str, default: int) -> int:
        raw = os.getenv(name)
        if raw is None or not str(raw).strip():
            return default
        try:
            return int(float(raw))
        except ValueError:
            return default

'''

    text = text.replace(
        "\n    def metrics(self) -> dict:\n",
        helper_methods + "    def metrics(self) -> dict:\n",
    )

    text = text.replace(
'''            "skipped_for_kill_switch": self.skipped_for_kill_switch,
            "blocked_symbols": len(self._blocked_until),
''',
'''            "skipped_for_kill_switch": self.skipped_for_kill_switch,
            "skipped_for_btc_filter": self.skipped_for_btc_filter,
            "skipped_for_edge": self.skipped_for_edge,
            "skipped_for_imbalance_confirmation": self.skipped_for_imbalance_confirmation,
            "round_trip_cost_bps": self.round_trip_cost_bps,
            "required_min_profit_bps": self.required_min_profit_bps,
            "required_expected_edge_bps": self.required_expected_edge_bps,
            "fee_adjusted_take_profit_bps": self._fee_adjusted_take_profit_bps(),
            "blocked_symbols": len(self._blocked_until),
'''
    )

strategy_path.write_text(text, encoding="utf-8")


symbol_path = Path("portfolio/symbol_discovery.py")
sym = symbol_path.read_text(encoding="utf-8", errors="replace")

if "import os" not in sym.splitlines()[:20]:
    sym = sym.replace("import logging\n", "import logging\nimport os\n")

if "AEGIS_SYMBOL_DISCOVERY_ALWAYS_INCLUDE" not in sym:
    sym = sym.replace(
'''    candidates.sort(key=lambda item: item.score, reverse=True)
    selected = tuple(item.symbol for item in candidates[:max_symbols])

    if selected:
        log.info(
            "Auto symbol discovery selected: %s",
            ", ".join(selected),
        )
        return selected
''',
'''    candidates.sort(key=lambda item: item.score, reverse=True)
    selected = tuple(item.symbol for item in candidates[:max_symbols])

    always_include = tuple(
        item.strip().upper()
        for item in os.getenv("AEGIS_SYMBOL_DISCOVERY_ALWAYS_INCLUDE", "").split(",")
        if item.strip()
    )

    if always_include:
        available = {symbol.upper(): symbol for symbol in markets.keys()}
        selected_list = list(selected)
        selected_upper = {symbol.upper() for symbol in selected_list}

        for requested in always_include:
            actual = available.get(requested, requested)
            if requested not in selected_upper and actual in markets:
                selected_list.append(actual)
                selected_upper.add(requested)

        selected = tuple(selected_list)

    if selected:
        log.info(
            "Auto symbol discovery selected: %s",
            ", ".join(selected),
        )
        return selected
'''
    )

symbol_path.write_text(sym, encoding="utf-8")


# Safe .env updater: avoids PowerShell reading huge .env into memory.
env_path = Path(".env")
if not env_path.exists():
    env_path.write_text("AEGIS_MODE=PAPER\n", encoding="utf-8")

if env_path.stat().st_size > 262_144:
    corrupt = Path(f".env.corrupt_phase3a")
    env_path.replace(corrupt)
    env_path.write_text("AEGIS_MODE=PAPER\n", encoding="utf-8")
    print(f"WARNING: .env was huge/corrupt and was renamed to {corrupt}. Re-add keys locally if needed.")

updates = {
    "AEGIS_MODE": "PAPER",
    "AEGIS_ENABLED_EXCHANGES": "binance",
    "AEGIS_EXECUTION_EXCHANGES": "binance",

    # Keep BTC in the data stream for market-regime filtering.
    "AEGIS_SYMBOL_DISCOVERY_ALWAYS_INCLUDE": "BTC/USDT",
    "AEGIS_BTC_FILTER_ENABLED": "true",
    "AEGIS_BTC_FILTER_REQUIRE_DATA": "true",
    "AEGIS_BTC_FILTER_SYMBOL": "BTC/USDT",
    "AEGIS_TRADE_BTC_SYMBOL": "false",
    "AEGIS_BTC_FILTER_MIN_OBSERVATIONS": "10",
    "AEGIS_BTC_FILTER_DANGER_DROP_BPS": "40",
    "AEGIS_BTC_FILTER_MAX_VOLATILITY_BPS": "85",

    # Fee/slippage-aware trading. 10 bps = 0.10% per side; tune from your real fills later.
    "AEGIS_STRATEGY_TAKER_FEE_BPS": "10",
    "AEGIS_STRATEGY_SLIPPAGE_BPS": "10",
    "AEGIS_STRATEGY_PROFIT_BUFFER_BPS": "10",
    "AEGIS_STRATEGY_EXPECTED_EDGE_MULTIPLIER": "1.4",

    # Stronger signal confirmation.
    "AEGIS_STRATEGY_IMBALANCE_CONFIRM_SNAPSHOTS": "3",

    # Volatility-aware stop.
    "AEGIS_STRATEGY_DYNAMIC_STOP_ENABLED": "true",
    "AEGIS_STRATEGY_DYNAMIC_STOP_MIN_BPS": "35",
    "AEGIS_STRATEGY_DYNAMIC_STOP_MAX_BPS": "85",
    "AEGIS_STRATEGY_DYNAMIC_STOP_MULTIPLIER": "1.5",
    "AEGIS_STRATEGY_DYNAMIC_STOP_LOOKBACK": "20",

    # Raise profit target enough to survive fee/slippage.
    "AEGIS_STRATEGY_TAKE_PROFIT_BPS": "75",
    "AEGIS_STRATEGY_STOP_LOSS_BPS": "35",
    "AEGIS_STRATEGY_MIN_PROFIT_AFTER_FEE_BPS": "35",
}

lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
seen = set()
out = []

for line in lines:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in line:
        out.append(line)
        continue

    key = line.split("=", 1)[0].strip()
    if key in updates:
        if key not in seen:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        continue

    out.append(line)

for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")

env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")

print("Phase 3A strategy + symbol discovery + env config patched.")
