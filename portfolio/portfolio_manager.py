class PortfolioManager:

    def __init__(self):

        self.positions = {}

    def update_position(
        self,
        symbol,
        quantity,
        price
    ):

        self.positions[symbol] = {

            'quantity': quantity,
            'price': price
        }

    def total_exposure(self):

        exposure = 0

        for symbol, pos in (
            self.positions.items()
        ):

            exposure += (
                pos['quantity']
                * pos['price']
            )

        return exposure

    def get_positions(self):

        return self.positions
