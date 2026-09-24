import threading
from copy import deepcopy


class StateManager:

    def __init__(self):

        self._lock = threading.RLock()

        self._state = {
            'positions': {},
            'balances': {},
            'orders': {},
            'market_data': {},
            'signals': {},
            'system': {
                'running': True
            }
        }

    def get(self, key, default=None):

        with self._lock:

            return deepcopy(
                self._state.get(key, default)
            )

    def set(self, key, value):

        with self._lock:

            self._state[key] = deepcopy(value)

    def update(self, key, value):

        with self._lock:

            if key not in self._state:
                self._state[key] = {}

            self._state[key].update(
                deepcopy(value)
            )

    def snapshot(self):

        with self._lock:

            return deepcopy(self._state)
