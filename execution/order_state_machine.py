from models.order import (
    OrderStatus
)


class InvalidStateTransition(
    Exception
):
    pass


class OrderStateMachine:

    VALID_TRANSITIONS = {

        OrderStatus.CREATED: [

            OrderStatus.VALIDATED,
            OrderStatus.REJECTED
        ],

        OrderStatus.VALIDATED: [

            OrderStatus.ROUTED,
            OrderStatus.FAILED,
            OrderStatus.REJECTED
        ],

        OrderStatus.ROUTED: [

            OrderStatus.SUBMITTED,
            OrderStatus.FAILED,
            OrderStatus.REJECTED
        ],

        OrderStatus.SUBMITTED: [

            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.FAILED
        ],

        OrderStatus.PARTIALLY_FILLED: [

            OrderStatus.FILLED,
            OrderStatus.CANCELLED
        ]
    }

    def transition(
        self,
        order,
        new_state
    ):

        valid = self.VALID_TRANSITIONS.get(
            order.status,
            []
        )

        if new_state not in valid:

            raise InvalidStateTransition(

                f'Invalid transition '

                f'{order.status} -> {new_state}'
            )

        order.status = new_state

        return order
