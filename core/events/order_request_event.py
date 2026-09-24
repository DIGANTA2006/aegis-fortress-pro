from dataclasses import dataclass, field

from core.events.base_event import BaseEvent


@dataclass
class OrderRequestEvent(BaseEvent):
    order_payload: dict = field(default_factory=dict)
    mark_prices: dict = field(default_factory=dict)
