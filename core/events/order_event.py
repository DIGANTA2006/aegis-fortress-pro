from dataclasses import dataclass

from core.events.base_event import (
    BaseEvent
)


@dataclass
class OrderEvent(BaseEvent):

    order_id: str = ''

    symbol: str = ''

    status: str = ''

    exchange: str = ''
