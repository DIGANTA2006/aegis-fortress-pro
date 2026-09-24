from typing import Any

from models.execution_report import ExecutionReport
from models.order import Order, OrderStatus


class ExchangeResponseNormalizer:
    STATUS_MAP = {
        "open": OrderStatus.SUBMITTED,
        "new": OrderStatus.SUBMITTED,
        "submitted": OrderStatus.SUBMITTED,
        "pending": OrderStatus.SUBMITTED,
        "partial": OrderStatus.PARTIALLY_FILLED,
        "partially_filled": OrderStatus.PARTIALLY_FILLED,
        "partiallyfilled": OrderStatus.PARTIALLY_FILLED,
        "closed": OrderStatus.FILLED,
        "filled": OrderStatus.FILLED,
        "done": OrderStatus.FILLED,
        "cancelled": OrderStatus.CANCELLED,
        "canceled": OrderStatus.CANCELLED,
        "rejected": OrderStatus.REJECTED,
        "failed": OrderStatus.FAILED,
    }

    def normalize(
        self,
        order: Order,
        exchange_name: str,
        raw_response: Any,
    ) -> ExecutionReport:
        payload = raw_response if isinstance(raw_response, dict) else {}

        raw_status = str(payload.get("status", "submitted")).lower()
        status = self.STATUS_MAP.get(raw_status, OrderStatus.SUBMITTED)

        filled_quantity = self._extract_float(
            payload,
            "filled",
            "filled_quantity",
            "executedQty",
            "amount_filled",
            default=0.0,
        )

        average_fill_price = self._extract_float(
            payload,
            "average",
            "avgPrice",
            "average_fill_price",
            "price",
            default=0.0,
        )

        exchange_order_id = (
            payload.get("id")
            or payload.get("orderId")
            or payload.get("clientOrderId")
        )

        fee = self._extract_fee(payload)

        if (
            filled_quantity > 0
            and filled_quantity < order.quantity
            and status == OrderStatus.SUBMITTED
        ):
            status = OrderStatus.PARTIALLY_FILLED

        if (
            filled_quantity >= order.quantity
            and order.quantity > 0
        ):
            status = OrderStatus.FILLED

        return ExecutionReport(
            symbol=order.symbol,
            side=order.side.value,
            requested_quantity=order.quantity,
            filled_quantity=filled_quantity,
            average_fill_price=average_fill_price,
            status=status,
            exchange=exchange_name,
            exchange_order_id=str(exchange_order_id) if exchange_order_id else None,
            correlation_id=order.correlation_id,
            fee=fee,
            raw_response=raw_response,
        )

    def _extract_float(
        self,
        payload: dict,
        *keys: str,
        default: float,
    ) -> float:
        for key in keys:
            value = payload.get(key)

            if isinstance(value, (int, float)):
                return float(value)

            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    continue

        return default

    def _extract_fee(self, payload: dict) -> float:
        total_fee = 0.0

        def add_fee_value(value) -> None:
            nonlocal total_fee

            if isinstance(value, (int, float)):
                total_fee += float(value)
                return

            if isinstance(value, str):
                try:
                    total_fee += float(value)
                except ValueError:
                    pass

        fee = payload.get("fee")

        if isinstance(fee, dict):
            add_fee_value(fee.get("cost"))
        else:
            add_fee_value(fee)

        fees = payload.get("fees")

        if isinstance(fees, list):
            for item in fees:
                if isinstance(item, dict):
                    add_fee_value(item.get("cost"))

        info = payload.get("info")

        if isinstance(info, dict):
            fills = info.get("fills")

            if isinstance(fills, list):
                for fill in fills:
                    if isinstance(fill, dict):
                        add_fee_value(fill.get("commission"))

            add_fee_value(info.get("commission"))

        return total_fee
