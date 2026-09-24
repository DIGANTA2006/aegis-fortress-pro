class PercentageFeeModel:
    def __init__(
        self,
        rate: float = 0.0004,
    ) -> None:
        if rate < 0:
            raise ValueError("Fee rate cannot be negative")

        self.rate = rate

    def calculate(
        self,
        quantity: float,
        price: float,
    ) -> float:
        if quantity <= 0 or price <= 0:
            return 0.0

        return quantity * price * self.rate
