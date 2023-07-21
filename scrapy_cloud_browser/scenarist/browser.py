from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scenarist.connection import Connection

from scrapy_cloud_browser.scenarist.page import Page


class Browser:
    def __init__(self, connection: 'Connection'):
        self._connection = connection

    async def ping(self):
        await self._connection.send('Browser.getVersion')

    async def new_page(self):
        target_id = (
            await self._connection.send('Target.createTarget', {'url': ''})
        )['targetId']
        session_id = (
            await self._connection.send(
                'Target.attachToTarget',
                {'targetId': target_id, 'flatten': True},
            )
        )['sessionId']

        await self._connection.send(
            'Fetch.enable',
            {'patterns': [{'requestStage': 'Request'}, {'requestStage': 'Response'}]},
            session_id=session_id,
        )
        return Page(target_id, session_id, self._connection)

    async def close(self):
        await self._connection.send('Browser.close')
