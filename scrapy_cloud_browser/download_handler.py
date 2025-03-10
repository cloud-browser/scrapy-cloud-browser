import asyncio
import itertools
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Optional, Union, Dict, Any

import anyio
import httpx
from scrapy import Request, Spider
from scrapy.crawler import Crawler
from scrapy.http import Headers, Response
from scrapy.responsetypes import responsetypes
from scrapy.utils.defer import deferred_from_coro
from scrapy.utils.reactor import verify_installed_reactor
from twisted.internet.defer import Deferred

from scrapy_cloud_browser.scenarist import connect
from scrapy_cloud_browser.scenarist.browser import Browser
from scrapy_cloud_browser.schemas import ProxyOrdering, SettingsScheme

logger = logging.getLogger(__name__)


@dataclass
class Options:
    host: str
    token: str
    timeout: int = 60
    init_handler: Optional[str] = None
    pages_per_browser: Optional[int] = None
    browser_settings: Optional[Dict[str, Any]] = None
    fingerprint: Optional[Dict[str, Any]] = None


class BrowserContextWrapperError(Exception):
    pass


class FakeSemaphore:
    async def release(self) -> None:
        pass

    async def acquire(self) -> None:
        pass


class ProxyManager:
    def __init__(
        self, proxies: Union[list[str], Callable[[], Awaitable[str]]], ordering: str
    ) -> None:
        ordering = ProxyOrdering(ordering)

        if isinstance(proxies, list):
            if not proxies:
                raise ValueError("Proxies list cannot be empty")

            if ordering == ProxyOrdering.ROUND_ROBIN:
                self._proxies = itertools.cycle(proxies)
            elif ordering == ProxyOrdering.RANDOM:
                self._proxies = proxies
            else:
                raise ValueError(f'Unknown ordering type: {ordering}')
        elif asyncio.iscoroutinefunction(proxies):
            self._proxies = proxies
        else:
            raise ValueError('Proxies must be a list or a coroutine function')

    async def get(self) -> str:
        if asyncio.iscoroutinefunction(self._proxies):
            return await self._proxies()
        elif isinstance(self._proxies, itertools.cycle):
            return str(next(self._proxies))
        else:
            return str(random.choice(self._proxies))


class BrowserContextWrapper:
    def __init__(
        self,
        num: int,
        browser_pool: asyncio.Queue,
        options: Options,
        start_sem: asyncio.Semaphore,
        proxy_manager: ProxyManager,
    ) -> None:
        self.num = num

        self._browser_pool = browser_pool
        self._options = options
        self._started = False
        self._wait = asyncio.Event()
        self.browser: Optional[Browser] = None
        self._last_ok_heartbeat = False
        self._heartbeat_interval = 5

        self._pages_per_browser_left: Optional[int] = None
        self._start_sem = start_sem
        self._proxy_manager = proxy_manager

    async def run(self):
        self._started = True
        logger.debug(f'{self.num}: RUN WORKER')
        self.start_heartbeat()
        while self._started:
            try:
                await self.connect()
                logger.debug(f'{self.num}: check connection')
                await self.check_connection()
                logger.debug(
                    f'{self.num}: put into queue with {self._browser_pool.qsize()} workers'
                )
                await self._browser_pool.put(self)
                # important: wait only if we put ourselves
                logger.debug(f'{self.num}: wait for next task')
                await self._wait.wait()
                self._wait.clear()
            except Exception:
                logger.exception(f'{self.num}: during worker loop')
                await self.close()
                continue

    def start_heartbeat(self) -> None:
        asyncio.create_task(self.heartbeat())

    async def heartbeat(self) -> None:
        while self._started:
            logger.debug(f'{self.num}: Heartbeat: {self._last_ok_heartbeat}')

            if self.browser:
                try:
                    await self.browser.ping()
                    self._last_ok_heartbeat = True
                except Exception:
                    logger.debug(f'{self.num}: Heartbeat ping failed')
                    self._last_ok_heartbeat = False
            else:
                self._last_ok_heartbeat = False

            await asyncio.sleep(self._heartbeat_interval)

    async def connect(self) -> None:
        logger.debug(f'{self.num}: connect')
        if self.is_established_connection():
            logger.debug(f'{self.num}: Established return')
            return

        proxy = await self._proxy_manager.get()
        ws_url = await self.get_ws_url(self._options, proxy)
        await asyncio.sleep(0.5)
        logger.debug(f'{self.num}: got ws: {ws_url}')
        with anyio.fail_after(10):
            browser: Browser = await connect(ws_url)

        logger.debug(f'{self.num}: got browser: {browser}')
        await self.on_connect(browser)

    async def on_connect(self, browser: Browser) -> None:
        self.browser = browser
        logger.debug(f'{self.num}: got browser: {self.browser}')

        self._last_ok_heartbeat = True  # noqa

        if self._options.pages_per_browser:
            self._pages_per_browser_left = self._options.pages_per_browser

    async def on_response(self, response: Optional[Response]):
        if response:
            logger.debug(f'{self.num}: Response: {response.status=} {response=}')

        if not response or response.status > 499:
            await self.close()

        if self._options.pages_per_browser:
            self._pages_per_browser_left -= 1
            if self._pages_per_browser_left == 0:
                await self.close()

        self._wait.set()

    async def close(self):
        logger.warning(f'{self.num}: Close browser')
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                logger.exception('During browser close')

            self.browser = None

    def is_established_connection(self) -> bool:
        return isinstance(self.browser, Browser)

    async def check_connection(self):
        try:
            await self.browser.ping()
        except:
            msg = f'{self.num}: Browser is not connected'
            raise BrowserContextWrapperError(msg)

    async def get_ws_url(self, options: Options, proxy: str) -> str:
        async with httpx.AsyncClient(base_url=options.host) as client:
            async with self._start_sem:
                request_data = {'proxy': proxy}

                if options.browser_settings:
                    request_data['browser_settings'] = options.browser_settings

                if options.fingerprint:
                    request_data['fingerprint'] = options.fingerprint

                resp = await client.post(
                    '/profiles/one_time',
                    json=request_data,
                    headers={'x-cloud-api-token': options.token},
                    timeout=options.timeout,
                )
                resp.raise_for_status()
                return resp.json()['ws_url']


class CloudBrowserHandler:
    def __init__(self, crawler: Crawler):
        verify_installed_reactor('twisted.internet.asyncioreactor.AsyncioSelectorReactor')

        self.crawler = crawler
        self.settings = SettingsScheme(**self.crawler.settings.get('CLOUD_BROWSER', {}))

        self.options = Options(
            host=str(self.settings.API_HOST),
            token=self.settings.API_TOKEN,
            init_handler=self.settings.INIT_HANDLER,
            pages_per_browser=self.settings.PAGES_PER_BROWSER,
            browser_settings=self.settings.BROWSER_SETTINGS,
            fingerprint=self.settings.FINGERPRINT,
        )

        self.browser_pool = asyncio.Queue()
        self.workers = []

        self.start_sem = asyncio.Semaphore(self.settings.START_SEMAPHORES)
        self.proxy_manager = ProxyManager(self.settings.PROXIES, self.settings.PROXY_ORDERING)

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> 'CloudBrowserHandler':
        return cls(crawler)

    def start_workers(self):
        logger.debug('START WORKERS')

        for i in range(self.settings.NUM_BROWSERS):
            self.workers.append(
                asyncio.create_task(
                    BrowserContextWrapper(
                        i, self.browser_pool, self.options, self.start_sem, self.proxy_manager
                    ).run()
                )
            )

    def download_request(self, request: Request, _: Spider) -> Deferred:
        logger.debug('download_request %s', request)
        return deferred_from_coro(self._download_request(request))

    async def get_browser(self) -> BrowserContextWrapper:
        while True:
            browser = await self.browser_pool.get()
            if browser._last_ok_heartbeat:
                return browser
            await browser.on_response(None)
            logger.debug('Browser is not ready, try another')
            await asyncio.sleep(0)

    async def _download_request(self, reqeust: Request):
        if not self.workers:
            self.start_workers()

        browser = await self.get_browser()
        response = None
        try:
            response = await self._get_response(reqeust, browser)
        finally:
            await browser.on_response(response)

        return response

    async def _get_response(self, request: Request, browser: BrowserContextWrapper):
        page = await browser.browser.new_page()
        headers = [
            {'name': name.decode(), 'value': value.decode()}
            for name, values in request.headers.items()
            for value in values
        ]

        try:
            response = await page.request(
                request.url,
                method=request.method,
                headers=headers,
            )
        finally:
            await page.close()

        scrapy_resp_headers = Headers()
        for header in response.headers:
            scrapy_resp_headers.appendlist(header['name'], header['value'])
        scrapy_resp_headers.pop('Content-Encoding', None)

        respcls = responsetypes.from_args(
            headers=scrapy_resp_headers,
            url=response.url,
            body=response.content,
        )
        return respcls(
            url=request.url,
            status=response.status_code,
            headers=scrapy_resp_headers,
            body=response.content,
            request=request,
        )
