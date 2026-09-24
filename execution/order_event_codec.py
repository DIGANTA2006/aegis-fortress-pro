from datetime import datetime

from models.order import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)


class OrderEventCodec:
    def encode(self, order: Order) -> dict:
        return {
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": order.quantity,
            "order_type": order.order_type.value,
            "price": order.price,
            "exchange": order.exchange,
            "status": order.status.value,
            "filled_quantity": order.filled_quantity,
            "average_fill_price": order.average_fill_price,
            "exchange_order_id": order.exchange_order_id,
            "strategy_id": order.strategy_id,
            "correlation_id": order.correlation_id,
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat(),
        }

    def decode(self, payload: dict) -> Order:
        if not isinstance(payload, dict):
            raise TypeError("Order event payload must be a dictionary")

        created_at = self._parse_datetime(payload.get("created_at"))
        updated_at = self._parse_datetime(payload.get("updated_at"))

        order = Order(
            symbol=str(payload["symbol"]),
            side=OrderSide(str(payload["side"]).upper()),
            quantity=float(payload["quantity"]),
            order_type=OrderType(str(payload["order_type"]).upper()),
            price=self._optional_float(payload.get("price")),
            exchange=payload.get("exchange"),
            status=OrderStatus(str(payload.get("status", "CREATED")).upper()),
            filled_quantity=float(payload.get("filled_quantity", 0.0)),
            average_fill_price=float(payload.get("average_fill_price", 0.0)),
            exchange_order_id=payload.get("exchange_order_id"),
            strategy_id=payload.get("strategy_id"),
            correlation_id=str(payload["correlation_id"])
            if payload.get("correlation_id")
            else None,
        )

        if created_at is not None:
            order.created_at = created_at

        if updated_at is not None:
            order.updated_at = updated_at

        return order

    def _optional_float(self, value):
        if value is None:
            return None
        return float(value)

    def _parse_datetime(self, value):
        if not value:
            return None

        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
