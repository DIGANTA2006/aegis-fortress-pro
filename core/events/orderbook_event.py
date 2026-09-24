from dataclasses import dataclass, field

from core.events.base_event import BaseEvent


@dataclass
class OrderBookEvent(BaseEvent):
    orderbook: dict = field(default_factory=dict)
