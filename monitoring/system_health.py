import time

import psutil


def health_check():
    return {
        "cpu_percent": psutil.cpu_percent(),
        "memory_percent": psutil.virtual_memory().percent,
        "timestamp": time.time(),
    }


if __name__ == "__main__":
    print(health_check())
