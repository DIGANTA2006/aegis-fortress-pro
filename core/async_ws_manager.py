import asyncio
import json
import logging
import websockets


log = logging.getLogger(__name__)


class AsyncWebsocketManager:

    def __init__(
        self,
        url,
        reconnect_delay=5
    ):

        self.url = url

        self.reconnect_delay = (
            reconnect_delay
        )

        self.running = False

        self.websocket = None

    async def connect(self):

        while True:

            try:

                self.websocket = await (
                    websockets.connect(
                        self.url
                    )
                )

                log.info(
                    'Websocket connected'
                )

                return

            except Exception as e:

                log.exception(

                    f'Connection failed: {e}'
                )

                await asyncio.sleep(
                    self.reconnect_delay
                )

    async def receive_loop(
        self,
        callback
    ):

        self.running = True

        while self.running:

            try:

                if self.websocket is None:

                    await self.connect()

                message = await (
                    self.websocket.recv()
                )

                payload = json.loads(
                    message
                )

                if asyncio.iscoroutinefunction(
                    callback
                ):

                    await callback(payload)

                else:

                    callback(payload)

            except Exception as e:

                log.exception(

                    f'Websocket error: {e}'
                )

                self.websocket = None

                await asyncio.sleep(
                    self.reconnect_delay
                )

    async def close(self):

        self.running = False

        if self.websocket:

            await self.websocket.close()
