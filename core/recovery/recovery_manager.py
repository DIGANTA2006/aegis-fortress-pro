import logging


log = logging.getLogger(__name__)


class RecoveryManager:

    def __init__(self):

        self.recovery_actions = []

    def register_action(
        self,
        action
    ):

        self.recovery_actions.append(
            action
        )

    async def recover(self):

        log.warning(
            'Starting recovery sequence'
        )

        for action in self.recovery_actions:

            try:

                if callable(action):

                    result = action()

                    if hasattr(
                        result,
                        '__await__'
                    ):

                        await result

            except Exception as e:

                log.exception(

                    f'Recovery failed: {e}'
                )

        log.info(
            'Recovery completed'
        )
