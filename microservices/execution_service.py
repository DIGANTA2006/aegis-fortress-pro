import asyncio
import logging

from core.events.order_request_event import OrderRequestEvent
from execution.order_event_codec import OrderEventCodec
from microservices.base_service import BaseService


log = logging.getLogger(__name__)


class ExecutionService(BaseService):
    def __init__(
        self,
        event_bus,
        execution_pipeline,
    ) -> None:
        super().__init__("execution-service")

        self.event_bus = event_bus
        self.execution_pipeline = execution_pipeline
        self.codec = OrderEventCodec()

        self.received_requests = 0
        self.accepted_requests = 0
        self.rejected_requests = 0
        self.failed_requests = 0

    async def on_start(self) -> None:
        self.event_bus.subscribe(
            "ORDER_REQUEST",
            self._on_order_request,
        )

        log.info("ExecutionService subscribed to ORDER_REQUEST")

    async def run(self) -> None:
        while self.running:
            self.heartbeat()
            await asyncio.sleep(1)

    async def _on_order_request(
        self,
        event: OrderRequestEvent,
    ) -> None:
        self.received_requests += 1

        try:
            order = self.codec.decode(
                event.order_payload
            )

            result = await self.execution_pipeline.submit(
                order=order,
                mark_prices=event.mark_prices,
            )

            if result.accepted:
                self.accepted_requests += 1
            else:
                self.rejected_requests += 1

            if result.error:
                self.failed_requests += 1

            log.info(
                "ExecutionService processed order %s accepted=%s status=%s",
                order.correlation_id,
                result.accepted,
                order.status.value,
            )

        except Exception as exc:
            self.failed_requests += 1

            log.exception(
                "ExecutionService failed to process order request: %s",
                exc,
            )

    def metrics(self) -> dict:
        return {
            "received_requests": self.received_requests,
            "accepted_requests": self.accepted_requests,
            "rejected_requests": self.rejected_requests,
            "failed_requests": self.failed_requests,
        }

    def health(self) -> dict:
        payload = super().health()
        payload["metrics"] = self.metrics()
        return payload
