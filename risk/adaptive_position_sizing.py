class AdaptivePositionSizing:

    def __init__(
        self,
        base_risk_pct=0.01
    ):

        self.base_risk_pct = (
            base_risk_pct
        )

    def calculate_size(
        self,
        balance,
        volatility,
        stop_distance
    ):

        adjusted_risk = (
            self.base_risk_pct
            / max(volatility, 0.001)
        )

        risk_amount = (
            balance * adjusted_risk
        )

        position_size = (
            risk_amount / stop_distance
        )

        return max(position_size, 0)
