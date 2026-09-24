import asyncio
import inspect
import logging
from dataclasses import dataclass

from core.events.execution_event import ExecutionEvent
from core.structured_logger import set_correlation_id
from execution.exchange_response_normalizer import ExchangeResponseNormalizer
from execution.execution_validator import ExecutionValidator
from execution.fill_processor import FillProcessingResult, FillProcessor
from execution.order_state_machine import OrderStateMachine
from models.execution_report import ExecutionReport
from models.order import Order, OrderStatus
from risk.pre_trade_risk import PreTradeRiskValidator, RiskDecision


log = logging.getLogger(__name__)


@dataclass
class ExecutionPipelineResult:
    accepted: bool
    order: Order
    risk_decision: RiskDecision | None = None
    execution_report: ExecutionReport | None = None
    fill_result: FillProcessingResult | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "order_status": self.order.status.value,
            "correlation_id": self.order.correlation_id,
            "risk_decision": (
                self.risk_decision.to_dict()
                if self.risk_decision
                else None
            ),
            "execution_report": (
                self.execution_report.to_dict()
                if self.execution_report
                else None
            ),
            "fill_result": (
                self.fill_result.to_dict()
                if self.fill_result
                else None
            ),
            "error": self.error,
        }


class ExecutionPipeline:
    def __init__(
        self,
        router,
        ledger,
        pre_trade_risk: PreTradeRiskValidator,
        fill_processor: FillProcessor,
        event_bus=None,
        database=None,
    ) -> None:
        self.router = router
        self.ledger = ledger
        self.pre_trade_risk = pre_trade_risk
        self.fill_processor = fill_processor
        self.event_bus = event_bus
        self.database = database

        self.validator = ExecutionValidator()
        self.state_machine = OrderStateMachine()
        self.normalizer = ExchangeResponseNormalizer()

    async def submit(
        self,
        order: Order,
        mark_prices: dict[str, float] | None = None,
    ) -> ExecutionPipelineResult:
        mark_prices = mark_prices or {}
        set_correlation_id(order.correlation_id)

        try:
            self.validator.validate(order)

            self.state_machine.transition(
                order,
                OrderStatus.VALIDATED,
            )

            route_result = self.router.find_best_exchange(
                symbol=order.symbol,
                side=order.side.value,
                quantity=order.quantity,
            )

            route_result = await self._maybe_await(route_result)

            if not route_result:
                raise RuntimeError("Router returned no exchange")

            exchange, reference_price = route_result

            if exchange is None:
                raise RuntimeError("No exchange available for order")

            if reference_price is None or reference_price <= 0:
                raise RuntimeError("Router returned invalid reference price")

            self._apply_exchange_precision(
                exchange=exchange,
                order=order,
            )

            exchange_min_notional = self._exchange_min_notional(
                exchange=exchange,
                symbol=order.symbol,
            )

            risk_decision = self.pre_trade_risk.validate(
                order=order,
                reference_price=reference_price,
                positions=self.ledger.positions(),
                mark_prices=mark_prices,
                min_order_notional_override=exchange_min_notional,
            )

            if not risk_decision.allowed:
                self.state_machine.transition(
                    order,
                    OrderStatus.REJECTED,
                )

                log.warning(
                    "Order rejected by pre-trade risk: %s",
                    risk_decision.reasons,
                )

                return ExecutionPipelineResult(
                    accepted=False,
                    order=order,
                    risk_decision=risk_decision,
                )

            self.state_machine.transition(
                order,
                OrderStatus.ROUTED,
            )

            order.exchange = getattr(
                exchange,
                "id",
                exchange.__class__.__name__,
            )

            raw_response = exchange.create_order(
                order.symbol,
                order.order_type.value.lower(),
                order.side.value.lower(),
                order.quantity,
                price=order.price,
            )

            raw_response = await self._maybe_await(raw_response)

            self.state_machine.transition(
                order,
                OrderStatus.SUBMITTED,
            )

            execution_report = self.normalizer.normalize(
                order=order,
                exchange_name=order.exchange,
                raw_response=raw_response,
            )

            if self.database is not None:
                self.database.record_execution_report(
                    execution_report
                )

            self._apply_report_status(
                order=order,
                execution_report=execution_report,
            )

            fill_result = self.fill_processor.process(
                report=execution_report,
                mark_prices=mark_prices,
                strategy_id=order.strategy_id,
            )

            await self._publish_execution_event(
                execution_report=execution_report,
                fill_result=fill_result,
            )

            return ExecutionPipelineResult(
                accepted=True,
                order=order,
                risk_decision=risk_decision,
                execution_report=execution_report,
                fill_result=fill_result,
            )

        except Exception as exc:
            order.status = OrderStatus.FAILED

            log.exception(
                "Execution pipeline failed: %s",
                exc,
            )

            return ExecutionPipelineResult(
                accepted=False,
                order=order,
                error=str(exc),
            )

        finally:
            set_correlation_id(None)

    def _apply_report_status(
        self,
        order: Order,
        execution_report: ExecutionReport,
    ) -> None:
        report_status = execution_report.status

        if report_status == OrderStatus.SUBMITTED:
            return

        try:
            self.state_machine.transition(
                order,
                report_status,
            )
        except Exception:
            order.status = report_status

        order.filled_quantity = execution_report.filled_quantity
        order.average_fill_price = execution_report.average_fill_price
        order.exchange_order_id = execution_report.exchange_order_id


    def _apply_exchange_precision(
        self,
        exchange,
        order: Order,
    ) -> None:
        amount_to_precision = getattr(exchange, "amount_to_precision", None)

        if callable(amount_to_precision):
            order.quantity = float(
                amount_to_precision(order.symbol, order.quantity)
            )

        if order.price is not None:
            price_to_precision = getattr(exchange, "price_to_precision", None)

            if callable(price_to_precision):
                order.price = float(
                    price_to_precision(order.symbol, order.price)
                )

    def _exchange_min_notional(
        self,
        exchange,
        symbol: str,
    ) -> float | None:
        min_order_notional = getattr(exchange, "min_order_notional", None)

        if not callable(min_order_notional):
            return None

        try:
            value = min_order_notional(symbol)
        except Exception:
            return None

        if value is None:
            return None

        try:
            value = float(value)
        except (TypeError, ValueError):
            return None

        if value <= 0:
            return None

        return value

    async def _publish_execution_event(
        self,
        execution_report: ExecutionReport,
        fill_result: FillProcessingResult,
    ) -> None:
        if self.event_bus is None:
            return

        event = ExecutionEvent(
            event_type="EXECUTION_REPORT",
            correlation_id=execution_report.correlation_id,
            report=execution_report.to_dict(),
            fill_result=fill_result.to_dict(),
        )

        publish_result = self.event_bus.publish(event)
        await self._maybe_await(publish_result)

    async def _maybe_await(self, value):
        if inspect.isawaitable(value):
            return await value

        return value
