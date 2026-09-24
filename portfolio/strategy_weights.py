class StrategyWeights:

    def calculate(
        self,
        performance
    ):

        total = sum(
            max(v, 0)
            for v in performance.values()
        )

        if total == 0:

            return {
                k: 0
                for k in performance
            }

        return {

            k: max(v, 0) / total

            for k, v in performance.items()
        }
