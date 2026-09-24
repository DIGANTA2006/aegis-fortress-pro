from abc import ABC, abstractmethod


class BaseStrategy(ABC):

    @abstractmethod
    def generate_signal(
        self,
        market_data
    ):
        pass
