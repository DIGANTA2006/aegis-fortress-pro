"""
watchdog.py  -  AEGIS PRO v2
Watchdog that runs in its own daemon thread and detects main-loop freeze.

Fix for v1 bug: the v1 watchdog ran in the SAME thread as the main loop,
so a frozen main loop would prevent the watchdog from firing.

This module starts a background thread that reads a heartbeat timestamp
written by the main loop. If the heartbeat goes stale beyond the timeout,
the watchdog restarts the process.
"""

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from config import PATHS, AegisConfig
from utils import atomic_write_json, safe_read_json

log = logging.getLogger("aegis.watchdog")


class Watchdog:
    """
    Background thread: polls heartbeat file every 30 seconds.
    If last_beat is older than cfg.heartbeat_timeout_secs, restart process.
    Rate-limits restarts to cfg.max_restarts_per_hour per hour.
    """

    POLL_INTERVAL = 30  # seconds between checks

    def __init__(self, cfg: AegisConfig):
        self.cfg = cfg
        self._heartbeat_path = Path(PATHS["heartbeat"])
        self._restart_path = Path(PATHS["restart_count"])
        self._running = threading.Event()
        self._running.set()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="watchdog")
        self._thread.start()
        log.info(
            f"Watchdog started (timeout={self.cfg.heartbeat_timeout_secs}s, "
            f"poll={self.POLL_INTERVAL}s)."
        )

    def stop(self) -> None:
        self._running.clear()

    # ------------------------------------------------------------------

    def beat(self) -> None:
        """
        Called by the main loop every iteration to signal liveness.
        Writes the current timestamp to the heartbeat file.
        """
        atomic_write_json(self._heartbeat_path, {"last_beat": time.time()})

    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while self._running.is_set():
            time.sleep(self.POLL_INTERVAL)
            try:
                self._check()
            except Exception as exc:
                log.warning(f"Watchdog check error: {exc}")

    def _check(self) -> None:
        data = safe_read_json(self._heartbeat_path, default={})
        last_beat = float(data.get("last_beat", 0))
        stale = time.time() - last_beat

        if last_beat == 0:
            # Heartbeat file not written yet - bot is still starting up
            return

        if stale > self.cfg.heartbeat_timeout_secs:
            log.critical(
                f"Watchdog: main loop has been silent for {stale:.0f}s "
                f"(limit={self.cfg.heartbeat_timeout_secs}s). Restarting."
            )
            if self._can_restart():
                self._restart()
            else:
                log.critical("Restart limit reached. Manual intervention required.")

    def _can_restart(self) -> bool:
        """Rate-limit: max N restarts per hour."""
        data = safe_read_json(self._restart_path, default={"count": 0, "window_start": 0})
        now = time.time()
        window_start = float(data.get("window_start", 0))
        count = int(data.get("count", 0))

        # Reset window if it's been more than 1 hour
        if now - window_start > 3600:
            count = 0
            window_start = now

        if count >= self.cfg.max_restarts_per_hour:
            return False

        data["count"] = count + 1
        data["window_start"] = window_start
        atomic_write_json(self._restart_path, data)
        return True

    def _restart(self) -> None:
        log.critical("Watchdog: restarting process now.")
        try:
            subprocess.Popen([sys.executable] + sys.argv)
        except Exception as exc:
            log.critical(f"Failed to spawn restart: {exc}")
        os._exit(1)  # os._exit bypasses atexit handlers that might hang
