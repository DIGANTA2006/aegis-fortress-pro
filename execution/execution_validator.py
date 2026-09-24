from models.order import (
    OrderType
)


class ExecutionValidator:

    def validate(self, order):

        if not order.symbol:

            raise ValueError(
                'Missing symbol'
            )

        if order.quantity <= 0:

            raise ValueError(
                'Invalid quantity'
            )

        if (

            order.order_type
            == OrderType.LIMIT

            and order.price is None
        ):

            raise ValueError(
                'Limit order requires price'
            )

        return True
