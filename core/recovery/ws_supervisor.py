import time

class WebSocketSupervisor:

    def __init__(self):

        self.reconnect_attempts = 0

    def reconnect(self):

        self.reconnect_attempts += 1
        time.sleep(2)

        return True
