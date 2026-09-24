import math
import statistics
from typing import Any


class PerformanceMetrics:
    def calculate(
        self,
        equity_values_or_trades: list[Any] | None = None,
        trade_pnls: list[float] | None = None,
        *,
        equity_values: list[float] | None = None,
    ) -> dict:
        if equity_values is not None:
            equity_values_or_trades = equity_values
        equity_values: list[float]

        if trade_pnls is None:
            source = equity_values_or_trades or []

            if source and isinstance(source[0], dict):
                trades = source

                trade_pnls = [
                    float(trade.get("pnl", 0.0))
                    for trade in trades
                ]

                equity_values = self._equity_from_trade_pnls(
                    trade_pnls
                )

            else:
                equity_values = [
                    float(value)
                    for value in source
                ]

                trade_pnls = []

        else:
            equity_values = [
                float(value)
                for value in (equity_values_or_trades or [])
            ]

            trade_pnls = [
                float(value)
                for value in trade_pnls
            ]

        total_pnl = sum(trade_pnls)

        wins = [
            pnl
            for pnl in trade_pnls
            if pnl > 0
        ]

        losses = [
            pnl
            for pnl in trade_pnls
            if pnl < 0
        ]

        trade_count = len(trade_pnls)

        win_rate_pct = (
            (len(wins) / trade_count) * 100.0
            if trade_count > 0
            else 0.0
        )

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))

        profit_factor = (
            gross_profit / gross_loss
            if gross_loss > 0
            else math.inf if gross_profit > 0 else 0.0
        )

        average_trade_pnl = (
            statistics.mean(trade_pnls)
            if trade_pnls
            else 0.0
        )

        if not equity_values:
            return {
                "total_pnl": total_pnl,
                "win_rate": win_rate_pct,
                "win_rate_pct": win_rate_pct,
                "avg_pnl": average_trade_pnl,
                "average_trade_pnl": average_trade_pnl,
                "max_win": max(wins) if wins else 0.0,
                "max_loss": min(losses) if losses else 0.0,
                "profit_factor": profit_factor,
                "trade_count": trade_count,
                "total_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "final_equity": 0.0,
            }

        initial_equity = equity_values[0]
        final_equity = equity_values[-1]

        total_return_pct = (
            ((final_equity - initial_equity) / initial_equity) * 100.0
            if initial_equity > 0
            else 0.0
        )

        returns = self._equity_returns(
            equity_values
        )

        return {
            "total_pnl": total_pnl,
            "win_rate": win_rate_pct,
            "win_rate_pct": win_rate_pct,
            "avg_pnl": average_trade_pnl,
            "average_trade_pnl": average_trade_pnl,
            "max_win": max(wins) if wins else 0.0,
            "max_loss": min(losses) if losses else 0.0,
            "profit_factor": profit_factor,
            "trade_count": trade_count,
            "total_return_pct": total_return_pct,
            "max_drawdown_pct": self._max_drawdown_pct(
                equity_values
            ),
            "sharpe_ratio": self._sharpe(
                returns
            ),
            "sortino_ratio": self._sortino(
                returns
            ),
            "final_equity": final_equity,
        }

    def _equity_from_trade_pnls(
        self,
        trade_pnls: list[float],
    ) -> list[float]:
        equity = 1.0
        curve = [equity]

        for pnl in trade_pnls:
            equity += pnl
            curve.append(equity)

        return curve

    def _equity_returns(
        self,
        values: list[float],
    ) -> list[float]:
        returns: list[float] = []

        for previous, current in zip(
            values,
            values[1:],
        ):
            if previous <= 0:
                continue

            returns.append(
                (current - previous) / previous
            )

        return returns

    def _sharpe(
        self,
        returns: list[float],
    ) -> float:
        if len(returns) < 2:
            return 0.0

        std_dev = statistics.stdev(returns)

        if std_dev == 0:
            return 0.0

        return (
            statistics.mean(returns)
            / std_dev
        ) * math.sqrt(len(returns))

    def _sortino(
        self,
        returns: list[float],
    ) -> float:
        if not returns:
            return 0.0

        downside = [
            value
            for value in returns
            if value < 0
        ]

        if len(downside) < 2:
            return 0.0

        downside_std = statistics.stdev(downside)

        if downside_std == 0:
            return 0.0

        return (
            statistics.mean(returns)
            / downside_std
        ) * math.sqrt(len(returns))

    def _max_drawdown_pct(
        self,
        values: list[float],
    ) -> float:
        peak = values[0]
        max_drawdown = 0.0

        for value in values:
            if value > peak:
                peak = value

            if peak <= 0:
                continue

            drawdown = (
                (peak - value) / peak
            ) * 100.0

            if drawdown > max_drawdown:
                max_drawdown = drawdown

        return max_drawdown