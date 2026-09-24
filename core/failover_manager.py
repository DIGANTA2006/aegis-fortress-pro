import logging

log = logging.getLogger(__name__)


class FailoverManager:

    def __init__(
        self,
        primary,
        backup
    ):

        self.primary = primary
        self.backup = backup

    def get_active_exchange(self):

        try:

            self.primary.fetch_balance()

            return self.primary

        except Exception as e:

            log.warning(
                f'Primary exchange failed: {e}'
            )

            return self.backup
