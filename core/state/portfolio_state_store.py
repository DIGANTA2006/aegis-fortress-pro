import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


class PortfolioStateStore:
    def __init__(self, path: str = "data/portfolio_state.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, payload: dict) -> None:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(self.path.parent),
            suffix=".tmp",
        ) as tmp:
            json.dump(payload, tmp, indent=2, sort_keys=True)
            temp_path = Path(tmp.name)

        os.replace(temp_path, self.path)

    def load(self) -> dict:
        if not self.path.exists():
            return {}

        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
