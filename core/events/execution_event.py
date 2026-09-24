from dataclasses import dataclass, field

from core.events.base_event import BaseEvent


@dataclass
class ExecutionEvent(BaseEvent):
    report: dict = field(default_factory=dict)
    fill_result: dict = field(default_factory=dict)
