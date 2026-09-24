from dataclasses import dataclass

from core.events.base_event import (
    BaseEvent
)


@dataclass
class MarketEvent(BaseEvent):

    symbol: str = ''

    price: float = 0.0

    volume: float = 0.0

    exchange: str = ''
