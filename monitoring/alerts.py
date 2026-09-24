import logging

log = logging.getLogger(__name__)


class AlertManager:

    def __init__(self):

        self.alerts = []

    def critical(self, message):

        log.critical(message)

        self.alerts.append({
            'level': 'CRITICAL',
            'message': message
        })

    def warning(self, message):

        log.warning(message)

        self.alerts.append({
            'level': 'WARNING',
            'message': message
        })

    def get_alerts(self):

        return self.alerts[-100:]
