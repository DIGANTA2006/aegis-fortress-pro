class ExchangeRegistry:

    def __init__(self):

        self.exchanges = {}

    def register(
        self,
        name,
        exchange
    ):

        self.exchanges[name] = exchange

    def get(self, name):

        return self.exchanges.get(name)

    def all(self):

        return self.exchanges
