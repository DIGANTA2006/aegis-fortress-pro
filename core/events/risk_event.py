from dataclasses import dataclass, field

from core.events.base_event import BaseEvent


@dataclass
class RiskEvent(BaseEvent):
    severity: str = "INFO"
    code: str = ""
    message: str = ""
    metadata: dict = field(default_factory=dict)
