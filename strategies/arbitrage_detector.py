class ArbitrageDetector:

    def detect(
        self,
        prices,
        threshold=0.5
    ):

        opportunities = []

        exchanges = list(prices.keys())

        for i in range(len(exchanges)):

            for j in range(i + 1, len(exchanges)):

                ex1 = exchanges[i]
                ex2 = exchanges[j]

                p1 = prices[ex1]
                p2 = prices[ex2]

                diff_pct = (
                    abs(p1 - p2)
                    / min(p1, p2)
                ) * 100

                if diff_pct >= threshold:

                    opportunities.append({

                        'buy_exchange': (
                            ex1 if p1 < p2 else ex2
                        ),

                        'sell_exchange': (
                            ex2 if p1 < p2 else ex1
                        ),

                        'difference_pct': diff_pct
                    })

        return opportunities
