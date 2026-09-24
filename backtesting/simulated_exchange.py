from dataclasses import dataclass
from itertools import count
from typing import Any

from backtesting.fee_model import PercentageFeeModel
from backtesting.slippage_model import BasisPointSlippageModel
from models.market_tick import MarketTick
from models.orderbook import OrderBookSnapshot


@dataclass
class SimulatedExchangeOrder:
    order_id: str
    symbol: str
    side: str
    order_type: str
    amount: float
    price: float | None
    status: str
    filled: float
    average: float
    fee: float

    def to_ccxt_like_payload(self) -> dict:
        return {
            "id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "type": self.order_type,
            "amount": self.amount,
            "price": self.price,
            "status": self.status,
            "filled": self.filled,
            "average": self.average,
            "fee": {
                "cost": self.fee,
            },
        }


class SimulatedExchange:
    id = "SIMULATED"

    def __init__(
        self,
        fee_model: PercentageFeeModel | None = None,
        slippage_model: BasisPointSlippageModel | None = None,
    ) -> None:
        self.fee_model = fee_model or PercentageFeeModel()
        self.slippage_model = slippage_model or BasisPointSlippageModel()

        self._ticks: dict[str, MarketTick] = {}
        self._orderbooks: dict[str, OrderBookSnapshot] = {}
        self._orders: dict[str, SimulatedExchangeOrder] = {}
        self._id_counter = count(1)

    def update_tick(
        self,
        tick: MarketTick,
    ) -> None:
        self._ticks[tick.symbol] = tick

    def update_orderbook(
        self,
        snapshot: OrderBookSnapshot,
    ) -> None:
        self._orderbooks[snapshot.symbol] = snapshot

    def fetch_ticker(
        self,
        symbol: str,
    ) -> dict:
        tick = self._ticks.get(symbol)

        if tick is None:
            raise RuntimeError(
                f"No simulated ticker available for {symbol}"
            )

        return {
            "symbol": symbol,
            "bid": tick.bid,
            "ask": tick.ask,
            "last": tick.last,
            "baseVolume": tick.volume,
            "timestamp": int(tick.timestamp.timestamp() * 1000),
        }

    def fetch_order_book(
        self,
        symbol: str,
        limit: int | None = None,
    ) -> dict:
        snapshot = self._orderbooks.get(symbol)

        if snapshot is None:
            raise RuntimeError(
                f"No simulated orderbook available for {symbol}"
            )

        bids = snapshot.bids
        asks = snapshot.asks

        if limit is not None and limit > 0:
            bids = bids[:limit]
            asks = asks[:limit]

        return {
            "symbol": symbol,
            "bids": [
                [level.price, level.quantity]
                for level in bids
            ],
            "asks": [
                [level.price, level.quantity]
                for level in asks
            ],
            "nonce": snapshot.sequence,
            "timestamp": int(snapshot.timestamp.timestamp() * 1000),
        }

    def get_best_bid(
        self,
        symbol: str,
    ) -> float:
        snapshot = self._orderbooks.get(symbol)

        if snapshot is not None and snapshot.best_bid > 0:
            return snapshot.best_bid

        tick = self._ticks.get(symbol)

        if tick is not None and tick.bid > 0:
            return tick.bid

        raise RuntimeError(
            f"No simulated bid available for {symbol}"
        )

    def get_best_ask(
        self,
        symbol: str,
    ) -> float:
        snapshot = self._orderbooks.get(symbol)

        if snapshot is not None and snapshot.best_ask > 0:
            return snapshot.best_ask

        tick = self._ticks.get(symbol)

        if tick is not None and tick.ask > 0:
            return tick.ask

        raise RuntimeError(
            f"No simulated ask available for {symbol}"
        )

    def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: float | None = None,
        params: dict | None = None,
    ) -> dict:
        if amount <= 0:
            raise ValueError("amount must be positive")

        normalized_type = str(type).lower()
        normalized_side = str(side).lower()

        if normalized_side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")

        if normalized_type not in {"market", "limit"}:
            raise ValueError("type must be market or limit")

        execution_price = self._determine_fill_price(
            symbol=symbol,
            order_type=normalized_type,
            side=normalized_side,
            limit_price=price,
        )

        if execution_price is None:
            order = self._build_order(
                symbol=symbol,
                side=normalized_side,
                order_type=normalized_type,
                amount=amount,
                price=price,
                status="open",
                filled=0.0,
                average=0.0,
                fee=0.0,
            )
            return order.to_ccxt_like_payload()

        fee = self.fee_model.calculate(
            quantity=amount,
            price=execution_price,
        )

        order = self._build_order(
            symbol=symbol,
            side=normalized_side,
            order_type=normalized_type,
            amount=amount,
            price=price,
            status="closed",
            filled=amount,
            average=execution_price,
            fee=fee,
        )

        return order.to_ccxt_like_payload()

    def _determine_fill_price(
        self,
        symbol: str,
        order_type: str,
        side: str,
        limit_price: float | None,
    ) -> float | None:
        side_upper = side.upper()

        if order_type == "market":
            reference = (
                self.get_best_ask(symbol)
                if side == "buy"
                else self.get_best_bid(symbol)
            )

            return self.slippage_model.apply(
                side=side_upper,
                reference_price=reference,
            )

        if limit_price is None or limit_price <= 0:
            raise ValueError("Limit order requires a positive price")

        if side == "buy":
            current_ask = self.get_best_ask(symbol)

            if limit_price >= current_ask:
                return min(
                    limit_price,
                    current_ask,
                )

            return None

        current_bid = self.get_best_bid(symbol)

        if limit_price <= current_bid:
            return max(
                limit_price,
                current_bid,
            )

        return None

    def _build_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        amount: float,
        price: float | None,
        status: str,
        filled: float,
        average: float,
        fee: float,
    ) -> SimulatedExchangeOrder:
        order_id = f"sim-{next(self._id_counter)}"

        order = SimulatedExchangeOrder(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            amount=amount,
            price=price,
            status=status,
            filled=filled,
            average=average,
            fee=fee,
        )

        self._orders[order_id] = order

        return order

    def order_snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            order_id: order.to_ccxt_like_payload()
            for order_id, order in self._orders.items()
        }
