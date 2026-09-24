import signal
import sys

shutdown_requested = False


def signal_handler(sig, frame):
    global shutdown_requested
    shutdown_requested = True
    print("Graceful shutdown requested...")


def register_signals() -> None:
    # Call this once from main.py - NOT at import time.
    signal.signal(signal.SIGINT, signal_handler)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, signal_handler)


# Auto-register but swallow errors if not in main thread
try:
    register_signals()
except (OSError, ValueError):
    pass
