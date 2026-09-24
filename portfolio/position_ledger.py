import threading
from datetime import datetime
from typing import Dict, Iterable

from models.position import Position
from models.trade import Trade


class PositionLedger:
    EPSILON = 1e-12

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._positions: Dict[str, Position] = {}
        self._trades: list[Trade] = []
        self._realized_pnl_total = 0.0

    def apply_fill(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        exchange: str,
        fee: float = 0.0,
        strategy_id: str | None = None,
        order_id: str | None = None,
    ) -> Trade:
        if not symbol:
            raise ValueError("symbol is required")

        if quantity <= 0:
            raise ValueError("quantity must be positive")

        if price <= 0:
            raise ValueError("price must be positive")

        normalized_side = side.upper()

        if normalized_side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")

        signed_delta = quantity if normalized_side == "BUY" else -quantity

        with self._lock:
            position = self._positions.get(symbol)

            if position is None:
                position = Position(symbol=symbol)

            realized_pnl = self._apply_signed_fill(
                position=position,
                signed_delta=signed_delta,
                price=price,
                fee=fee,
            )

            self._realized_pnl_total += realized_pnl

            position.updated_at = datetime.utcnow()

            if abs(position.quantity) <= self.EPSILON:
                position.quantity = 0.0
                position.average_entry = 0.0
                self._positions.pop(symbol, None)
            else:
                self._positions[symbol] = position

            trade = Trade(
                symbol=symbol,
                side=normalized_side,
                quantity=quantity,
                price=price,
                exchange=exchange,
                pnl=realized_pnl,
                fee=fee,
                strategy_id=strategy_id,
                order_id=order_id,
            )

            self._trades.append(trade)

            return trade

    def _apply_signed_fill(
        self,
        position: Position,
        signed_delta: float,
        price: float,
        fee: float,
    ) -> float:
        current_qty = position.quantity
        incoming_qty = signed_delta

        if abs(current_qty) <= self.EPSILON:
            position.quantity = incoming_qty
            position.average_entry = price
            return -fee

        same_direction = (
            current_qty > 0 and incoming_qty > 0
        ) or (
            current_qty < 0 and incoming_qty < 0
        )

        if same_direction:
            new_abs_qty = abs(current_qty) + abs(incoming_qty)

            weighted_cost = (
                abs(current_qty) * position.average_entry
                + abs(incoming_qty) * price
            )

            position.quantity = current_qty + incoming_qty
            position.average_entry = weighted_cost / new_abs_qty

            return -fee

        close_qty = min(abs(current_qty), abs(incoming_qty))

        if current_qty > 0:
            realized_pnl = (
                price - position.average_entry
            ) * close_qty
        else:
            realized_pnl = (
                position.average_entry - price
            ) * close_qty

        remaining_qty = current_qty + incoming_qty

        if abs(remaining_qty) <= self.EPSILON:
            position.quantity = 0.0
            position.average_entry = 0.0

        elif (
            current_qty > 0 > remaining_qty
        ) or (
            current_qty < 0 < remaining_qty
        ):
            position.quantity = remaining_qty
            position.average_entry = price

        else:
            position.quantity = remaining_qty

        net_realized = realized_pnl - fee
        position.realized_pnl += net_realized

        return net_realized

    def mark_positions(
        self,
        prices: dict[str, float],
    ) -> None:
        with self._lock:
            for symbol, position in self._positions.items():
                mark_price = prices.get(symbol)

                if mark_price is not None and mark_price > 0:
                    position.mark_to_market(mark_price)

    def get_position(
        self,
        symbol: str,
    ) -> Position | None:
        with self._lock:
            position = self._positions.get(symbol)

            if position is None:
                return None

            return Position(
                symbol=position.symbol,
                quantity=position.quantity,
                average_entry=position.average_entry,
                realized_pnl=position.realized_pnl,
                unrealized_pnl=position.unrealized_pnl,
                updated_at=position.updated_at,
            )

    def positions(self) -> dict[str, Position]:
        with self._lock:
            return {
                symbol: Position(
                    symbol=position.symbol,
                    quantity=position.quantity,
                    average_entry=position.average_entry,
                    realized_pnl=position.realized_pnl,
                    unrealized_pnl=position.unrealized_pnl,
                    updated_at=position.updated_at,
                )
                for symbol, position in self._positions.items()
            }

    def position_quantities(self) -> dict[str, float]:
        with self._lock:
            return {
                symbol: position.quantity
                for symbol, position in self._positions.items()
            }

    def realized_pnl(self) -> float:
        with self._lock:
            return self._realized_pnl_total


    def restore_snapshot(
        self,
        payload: dict,
    ) -> None:
        """Restore open positions from a saved portfolio snapshot.

        This is intentionally conservative: it only restores the position
        quantities/average entries that were previously saved by the runtime.
        It does not invent trades or reconcile unknown manual exchange balances.
        """
        if not isinstance(payload, dict):
            return

        positions = payload.get("positions", {})
        if not isinstance(positions, dict):
            return

        restored: dict[str, Position] = {}

        for symbol, raw_position in positions.items():
            if not isinstance(raw_position, dict):
                continue

            try:
                quantity = float(raw_position.get("quantity", 0.0) or 0.0)
                average_entry = float(raw_position.get("average_entry", 0.0) or 0.0)
                realized_pnl = float(raw_position.get("realized_pnl", 0.0) or 0.0)
                unrealized_pnl = float(raw_position.get("unrealized_pnl", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue

            if abs(quantity) <= self.EPSILON or average_entry <= 0:
                continue

            updated_at_raw = raw_position.get("updated_at")
            updated_at = datetime.utcnow()

            if isinstance(updated_at_raw, str) and updated_at_raw:
                try:
                    updated_at = datetime.fromisoformat(
                        updated_at_raw.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                except ValueError:
                    updated_at = datetime.utcnow()

            restored[str(symbol)] = Position(
                symbol=str(symbol),
                quantity=quantity,
                average_entry=average_entry,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                updated_at=updated_at,
            )

        with self._lock:
            self._positions = restored
            self._realized_pnl_total = float(
                payload.get("realized_pnl_total", 0.0) or 0.0
            )

    def trades(self) -> Iterable[Trade]:
        with self._lock:
            return tuple(self._trades)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "positions": {
                    symbol: position.to_dict()
                    for symbol, position in self._positions.items()
                },
                "trade_count": len(self._trades),
                "realized_pnl_total": self._realized_pnl_total,
            }
