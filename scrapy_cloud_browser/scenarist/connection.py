import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Optional

import websockets

from scrapy_cloud_browser.scenarist.errors import ScenaristError

logger = logging.getLogger(__name__)


class Connection:
    def __init__(self, ws_url: str):
        self._ws_url = ws_url

        self._last_id = 0

        self._messages = asyncio.Queue()
        self._main_loop_task = asyncio.create_task(self._main_loop())

        self._callbacks: dict[int, asyncio.Future] = {}
        self._event_handlers: dict[str, set[Callable]] = defaultdict(set)
        self._session_event_handlers: dict[str, set[Callable]] = defaultdict(set)

    async def send(
        self, method: str, params: Optional[dict] = None, *, session_id: Optional[str] = None
    ):
        self._last_id += 1

        callback = asyncio.Future()
        self._callbacks[self._last_id] = callback

        params = params or {}
        payload = {
            'id': self._last_id,
            'method': method,
            'params': params,
        }
        if session_id:
            payload['sessionId'] = session_id

        await self._messages.put(json.dumps(payload))
        return await callback

    async def _main_loop(self):
        logger.debug('Connect to browser through ws url: %s', self._ws_url)
        while True:
            async with websockets.connect(self._ws_url, max_size=2**32) as websocket:
                producer_task = asyncio.create_task(self._events_producer(websocket))
                consumer_task = asyncio.create_task(self._events_consumer(websocket))

                _, pending = await asyncio.wait(
                    [producer_task, consumer_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()

    async def _events_producer(self, websocket):
        while True:
            message = await self._messages.get()
            logger.debug('SEND: %s', message)
            await websocket.send(message)

    async def _events_consumer(self, websocket):
        try:
            async for message in websocket:
                asyncio.create_task(self._handle_event(json.loads(message)))
        except:
            logger.debug('Websocket disconnected')

    def add_handler(
        self,
        method: str,
        handler: Callable[[dict], Awaitable[None]],
        *,
        session_id: Optional[str] = None,
    ):
        if session_id:
            key = f'{method}:{session_id}'
            self._session_event_handlers[key].add(handler)
        else:
            self._event_handlers[method].add(handler)

    def remove_handler(
        self,
        method: str,
        handler: Callable[[dict], Awaitable[None]],
        *,
        session_id: Optional[str] = None,
    ):
        if session_id:
            key = f'{method}:{session_id}'
            handlers = self._session_event_handlers.get(key, set())
        else:
            handlers = self._event_handlers.get(method, set())

        handlers.discard(handler)
        if session_id:
            key = f'{method}:{session_id}'
            self._session_event_handlers.pop(key, None)
        else:
            self._event_handlers.pop(method, None)

    async def _handle_event(self, event: dict):
        logger.debug('RECV: %s', event)

        if callback := self._callbacks.pop(event.get('id'), None):
            if (result := event.get('result')) is not None:
                callback.set_result(result)
            else:
                error = event['error']
                callback.set_exception(ScenaristError(error['code'], error['message']))
        elif method := event.get('method'):
            if session_id := event.get('sessionId'):
                key = f'{method}:{session_id}'
                handlers = self._session_event_handlers.get(key, [])
            else:
                handlers = self._event_handlers.get(method, [])

            for handler in handlers:
                asyncio.create_task(handler(event['params']))
