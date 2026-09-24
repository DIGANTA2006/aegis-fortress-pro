import logging

log = logging.getLogger(__name__)


class StrategyManager:

    def __init__(self):

        self.strategies = {}

    def register(self, name, strategy):

        self.strategies[name] = strategy

        log.info(
            f'Strategy registered: {name}'
        )

    def run_all(self, market_data):

        signals = {}

        for name, strategy in self.strategies.items():

            try:

                signal = strategy.generate_signal(
                    market_data
                )

                signals[name] = signal

            except Exception as e:

                log.exception(
                    f'Strategy failed: {name} | {e}'
                )

        return signals
