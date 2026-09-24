class CapitalAllocator:

    def allocate(
        self,
        balance,
        strategies
    ):

        allocation = {}

        weight = (
            1 / max(len(strategies), 1)
        )

        for strategy in strategies:

            allocation[strategy] = (
                balance * weight
            )

        return allocation
