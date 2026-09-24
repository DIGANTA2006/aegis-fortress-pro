from dataclasses import dataclass, field

from core.events.base_event import BaseEvent


@dataclass
class MarketTickEvent(BaseEvent):
    tick: dict = field(default_factory=dict)
