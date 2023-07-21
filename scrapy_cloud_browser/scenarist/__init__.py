from scrapy_cloud_browser.scenarist.browser import Browser
from scrapy_cloud_browser.scenarist.connection import Connection


async def connect(browser_ws_url: str) -> Browser:
    connection = Connection(browser_ws_url)
    browser = Browser(connection)
    await browser.ping()

    return browser
