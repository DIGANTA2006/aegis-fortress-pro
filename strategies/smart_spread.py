class SmartSpread:

    def calculate_spread(
        self,
        base_spread,
        volatility,
        liquidity_score
    ):

        spread = base_spread

        spread *= (
            1 + volatility
        )

        if liquidity_score < 1000:
            spread *= 1.5

        return spread
