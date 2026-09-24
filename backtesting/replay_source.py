import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


@dataclass
class ReplayRecord:
    event_type: str
    timestamp: datetime
    payload: dict


class ReplaySource:
    def __init__(
        self,
        file_path: str,
    ) -> None:
        self.file_path = Path(file_path)

        if not self.file_path.exists():
            raise FileNotFoundError(
                f"Replay file not found: {self.file_path}"
            )

    def records(self) -> Iterator[ReplayRecord]:
        with self.file_path.open(
            "r",
            encoding="utf-8",
        ) as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()

                if not line:
                    continue

                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid JSON at replay line {line_number}"
                    ) from exc

                event_type = str(
                    row.get("event_type", "")
                ).upper()

                if event_type not in {
                    "MARKET_TICK",
                    "ORDERBOOK_SNAPSHOT",
                }:
                    raise ValueError(
                        f"Unsupported replay event type at line {line_number}: "
                        f"{event_type!r}"
                    )

                timestamp = self._parse_timestamp(
                    row.get("timestamp"),
                    line_number,
                )

                payload = row.get("payload")

                if not isinstance(payload, dict):
                    raise ValueError(
                        f"Replay payload must be a dictionary at line {line_number}"
                    )

                yield ReplayRecord(
                    event_type=event_type,
                    timestamp=timestamp,
                    payload=payload,
                )

    def _parse_timestamp(
        self,
        value,
        line_number: int,
    ) -> datetime:
        if isinstance(value, (int, float)):
            seconds = float(value)

            if seconds > 1_000_000_000_000:
                seconds /= 1000.0

            return datetime.fromtimestamp(
                seconds,
                tz=timezone.utc,
            ).replace(tzinfo=None)

        if isinstance(value, str):
            try:
                normalized = value.replace("Z", "+00:00")
                parsed = datetime.fromisoformat(normalized)

                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

                return parsed
            except ValueError as exc:
                raise ValueError(
                    f"Invalid replay timestamp at line {line_number}"
                ) from exc

        raise ValueError(
            f"Missing replay timestamp at line {line_number}"
        )
