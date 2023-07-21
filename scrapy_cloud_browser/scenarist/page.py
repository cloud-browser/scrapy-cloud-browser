import asyncio
import base64
import logging
from typing import TYPE_CHECKING, Literal, TypedDict, Optional

if TYPE_CHECKING:
    from scrapy_cloud_browser.scenarist.connection import Connection

logger = logging.getLogger(__name__)

REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}

MethodType = Literal['GET', 'OPTIONS', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE']


class HeaderEntryType(TypedDict):
    name: str
    value: str


class Response:
    def __init__(
        self,
        url: str,
        status_code: int,
        headers: list[HeaderEntryType],
        content: bytes,
    ):
        self._url = url
        self._status_code = status_code
        self._headers = headers

        self._content = content
        self._text = None

    @property
    def url(self) -> str:
        return self._url

    @property
    def status_code(self) -> int:
        return self._status_code

    @property
    def headers(self) -> list[HeaderEntryType]:
        return self._headers

    @property
    def content(self) -> bytes:
        return self._content

    @property
    def text(self) -> str:
        if self._text is None:
            self._text = self._content.decode()

        return self._text


class Page:
    def __init__(self, target_id: str, session_id: str, connection: 'Connection'):
        self._target_id = target_id
        self._session_id = session_id

        self._connection = connection

        self._request_in_progress = False
        self._closed = False

    async def _dummy_interceptor(self, params: dict):
        if self._closed:
            return

        request_id = params['requestId']
        await self._connection.send(
            'Fetch.continueRequest',
            {'requestId': request_id},
            session_id=self._session_id,
        )

    async def request(
        self,
        url: str,
        method: MethodType = 'GET',
        post_data: Optional[str] = None,
        headers: Optional[list[HeaderEntryType]] = None,
    ) -> Response:
        if self._closed:
            raise Exception('Page is closed')

        self._request_in_progress = True

        self._connection.remove_handler(
            'Fetch.requestPaused',
            self._dummy_interceptor,
            session_id=self._session_id,
        )

        response: asyncio.Future[Response] = asyncio.Future()

        async def interceptor(params: dict):
            request_id = params['requestId']

            status_code = params.get('responseStatusCode')
            location_header = next(
                (
                    header for header in params.get('responseHeaders', [])
                    if header['name'].lower() == 'location'
                ),
                None
            )
            if (
                status_code and
                not (status_code in REDIRECT_STATUS_CODES and location_header)
            ):
                content = await self._connection.send(
                    'Fetch.getResponseBody',
                    {'requestId': request_id},
                    session_id=self._session_id,
                )
                nonlocal response
                response.set_result(Response(
                    params['request']['url'],
                    params['responseStatusCode'],
                    params['responseHeaders'],
                    base64.b64decode(content['body']),
                ))

                self._connection.remove_handler(
                    'Fetch.requestPaused',
                    interceptor,
                    session_id=self._session_id
                )
                self._connection.add_handler(
                    'Fetch.requestPaused',
                    self._dummy_interceptor,
                    session_id=self._session_id,
                )

            overrides = {'method': method}
            if post_data:
                overrides['postData'] = post_data
            if headers:
                overrides['headers'] = headers

            await self._connection.send(
                'Fetch.continueRequest',
                {
                    'requestId': request_id,
                    **overrides,
                },
                session_id=self._session_id,
            )

        self._connection.add_handler(
            'Fetch.requestPaused',
            interceptor,
            session_id=self._session_id,
        )
        await self._connection.send(
            'Page.navigate',
            {'url': url},
            session_id=self._session_id,
        )

        self._request_in_progress = False
        return await response

    async def screenshot(self, path: str):
        result = await self._connection.send(
            'Page.captureScreenshot',
            session_id=self._session_id,
        )
        with open(path, 'w') as file:
            file.write(result['data'])

    async def close(self):
        while self._request_in_progress:
            await asyncio.sleep(0.5)

        self._closed = True
        self._connection.remove_handler(
            'Page.requestPaused',
            self._dummy_interceptor,
            session_id=self._session_id,
        )

        await self._connection.send(
            'Target.closeTarget',
            {'targetId': self._target_id},
            session_id=self._session_id,
        )
