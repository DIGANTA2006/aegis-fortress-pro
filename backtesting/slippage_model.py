class BasisPointSlippageModel:
    def __init__(
        self,
        bps: float = 2.0,
    ) -> None:
        if bps < 0:
            raise ValueError("Slippage basis points cannot be negative")

        self.bps = bps

    def apply(
        self,
        side: str,
        reference_price: float,
    ) -> float:
        if reference_price <= 0:
            raise ValueError("Reference price must be positive")

        multiplier = self.bps / 10000.0
        normalized_side = str(side).upper()

        if normalized_side == "BUY":
            return reference_price * (1.0 + multiplier)

        if normalized_side == "SELL":
            return reference_price * (1.0 - multiplier)

        raise ValueError("side must be BUY or SELL")
