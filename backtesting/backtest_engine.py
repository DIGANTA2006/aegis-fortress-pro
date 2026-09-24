class BacktestEngine:

    def __init__(
        self,
        strategy,
        initial_balance=10000
    ):

        self.strategy = strategy

        self.balance = initial_balance

        self.position = 0

        self.trade_history = []

    def run(self, historical_data):

        for candle in historical_data:

            signal = self.strategy.generate_signal(
                candle
            )

            price = candle['close']

            if signal == 'BUY':

                self.position += 1

                self.trade_history.append({
                    'action': 'BUY',
                    'price': price
                })

            elif signal == 'SELL' and self.position > 0:

                self.position -= 1

                pnl = (
                    price
                    - self.trade_history[-1]['price']
                )

                self.balance += pnl

                self.trade_history.append({
                    'action': 'SELL',
                    'price': price,
                    'pnl': pnl
                })

        return {
            'final_balance': self.balance,
            'trades': self.trade_history
        }
