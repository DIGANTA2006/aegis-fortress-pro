import time

class MetricsCollector:

    def __init__(self):

        self.metrics = {
            "orders_sent": 0,
            "orders_failed": 0,
            "ws_reconnects": 0,
            "latency_ms": [],
            "exceptions": 0
        }

    def increment(self, key):

        if key in self.metrics:
            self.metrics[key] += 1

    def record_latency(self, latency: float) -> None:
        # Record latency sample; cap at 1000 entries.
        self.metrics["latency_ms"].append(latency)
        if len(self.metrics["latency_ms"]) > 1000:
            self.metrics["latency_ms"] = self.metrics["latency_ms"][-1000:]

    def snapshot(self) -> dict:
        lat = self.metrics["latency_ms"]
        avg_lat = sum(lat) / len(lat) if lat else 0.0
        return {
            "timestamp": time.time(),
            "avg_latency_ms": round(avg_lat, 3),
            "metrics": self.metrics,
        }
