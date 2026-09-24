import logging

from execution.order_state_machine import (
    OrderStateMachine
)

from execution.execution_validator import (
    ExecutionValidator
)

from models.order import (
    OrderStatus
)

log = logging.getLogger(__name__)


class ExecutionGateway:

    def __init__(
        self,
        router
    ):

        self.router = router

        self.validator = (
            ExecutionValidator()
        )

        self.state_machine = (
            OrderStateMachine()
        )

    async def execute(
        self,
        order
    ):

        try:

            self.validator.validate(
                order
            )

            self.state_machine.transition(

                order,

                OrderStatus.VALIDATED
            )

            exchange, price = (

                self.router.find_best_exchange(

                    order.symbol,

                    order.side,

                    order.quantity
                )
            )

            self.state_machine.transition(

                order,

                OrderStatus.ROUTED
            )

            order.exchange = getattr(

                exchange,

                'id',

                'UNKNOWN'
            )

            response = await exchange.create_order(

                symbol=order.symbol,

                type=order.order_type.value.lower(),

                side=order.side.value.lower(),

                amount=order.quantity,

                price=order.price
            )

            order.exchange_order_id = (

                response.get('id')
            )

            self.state_machine.transition(

                order,

                OrderStatus.SUBMITTED
            )

            log.info(

                f'Order submitted '

                f'{order.correlation_id}'
            )

            return order

        except Exception as e:

            order.status = (
                OrderStatus.FAILED
            )

            log.exception(

                f'Execution failed: {e}'
            )

            return order
