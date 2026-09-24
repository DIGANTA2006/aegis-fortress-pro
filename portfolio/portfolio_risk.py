class PortfolioRisk:

    def max_position_check(
        self,
        portfolio_value,
        position_value,
        max_pct=0.2
    ):

        exposure_pct = (
            position_value / portfolio_value
        )

        return exposure_pct <= max_pct
