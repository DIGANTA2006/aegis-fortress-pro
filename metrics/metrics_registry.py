"""
Central metrics registry for Aegis v2.
Tracks counters, gauges, and histograms for trading operations.
"""
import time
import threading
from collections import defaultdict


class MetricsRegistry:
    """Thread-safe metrics registry."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._timestamps: dict[str, float] = {}

    # ---------- Counters ----------

    def increment(self, name: str, value: float = 1.0, labels: dict | None = None) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] += value
            self._timestamps[key] = time.time()

    def get_counter(self, name: str, labels: dict | None = None) -> float:
        return self._counters.get(self._key(name, labels), 0.0)

    # ---------- Gauges ----------

    def set_gauge(self, name: str, value: float, labels: dict | None = None) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._gauges[key] = value
            self._timestamps[key] = time.time()

    def get_gauge(self, name: str, labels: dict | None = None) -> float | None:
        return self._gauges.get(self._key(name, labels))

    # ---------- Histograms ----------

    def observe(self, name: str, value: float, labels: dict | None = None) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._histograms[key].append(value)
            self._timestamps[key] = time.time()

    def get_histogram(self, name: str, labels: dict | None = None) -> list[float]:
        return list(self._histograms.get(self._key(name, labels), []))

    def histogram_summary(self, name: str, labels: dict | None = None) -> dict:
        data = self.get_histogram(name, labels)
        if not data:
            return {}
        data_sorted = sorted(data)
        n = len(data_sorted)
        return {
            "count": n,
            "sum": sum(data_sorted),
            "min": data_sorted[0],
            "max": data_sorted[-1],
            "mean": sum(data_sorted) / n,
            "p50": data_sorted[int(n * 0.50)],
            "p95": data_sorted[int(n * 0.95)],
            "p99": data_sorted[int(n * 0.99)],
        }

    # ---------- Snapshot ----------

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histogram_counts": {k: len(v) for k, v in self._histograms.items()},
                "captured_at": time.time(),
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._timestamps.clear()

    # ---------- Helpers ----------

    @staticmethod
    def _key(name: str, labels: dict | None) -> str:
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"
