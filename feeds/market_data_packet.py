from dataclasses import dataclass
from typing import Any


@dataclass
class MarketDataPacket:
    kind: str
    exchange: str
    symbol: str
    payload: Any
