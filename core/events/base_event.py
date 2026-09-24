from dataclasses import dataclass, field
from datetime import datetime
import uuid


@dataclass
class BaseEvent:

    event_type: str

    correlation_id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )

    timestamp: datetime = field(
        default_factory=datetime.utcnow
    )
