import json
from pathlib import Path


class StateSnapshotManager:

    def __init__(
        self,
        snapshot_file='state_snapshot.json'
    ):

        self.snapshot_file = (
            Path(snapshot_file)
        )

    def save(self, state):

        with open(
            self.snapshot_file,
            'w'
        ) as f:

            json.dump(
                state,
                f,
                indent=2
            )

    def load(self):

        if not self.snapshot_file.exists():

            return {}

        with open(
            self.snapshot_file,
            'r'
        ) as f:

            return json.load(f)
