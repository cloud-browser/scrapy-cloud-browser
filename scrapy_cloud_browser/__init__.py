import logging

from scrapy_cloud_browser.download_handler import CloudBrowserHandler
from scrapy_cloud_browser.extension import CloudBrowserExtension

logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)

__all__ = [
    'CloudBrowserHandler',
    'CloudBrowserExtension',
]
