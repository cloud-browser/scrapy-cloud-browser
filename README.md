# scrapy-cloud-browser

[![PyPI - Version](https://img.shields.io/pypi/v/scrapy-cloud-browser.svg)](https://pypi.org/project/scrapy-cloud-browser)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/scrapy-cloud-browser.svg)](https://pypi.org/project/scrapy-cloud-browser)

A Scrapy extension that integrates with [surfsky.io](https://surfsky.io) for web scraping. This extension allows you to use Chrome anti-detection browsers through Surfsky.io's cloud browser service, helping you avoid detection while scraping challenging websites.

-----

## Installation

```console
pip install scrapy-cloud-browser
```

## Usage

Setup environment variables in `settings.py` in `CLOUD_BROWSER` namespace:

```python
CLOUD_BROWSER = {
    "API_HOST": <HOST>,
    "API_TOKEN": <API_TOKEN>,
    "NUM_BROWSERS": <NUM_BROWSERS>,
    "PROXIES": [<proxy>],
    "PAGES_PER_BROWSER": <PAGES_PER_BROWSER>,
    "START_SEMAPHORES": <START_SEMAPHORES>,
    "PROXY_ORDERING": <PROXY_ORDERING>,
    "BROWSER_SETTINGS: <BROWSER_SETTINGS>,
    "FINGERPRINT": <FINGERPRINT>
}
```

### Configuration Parameters

- **API_HOST**: The URL of the Surfsky.io API host.
- **API_TOKEN**: Your authentication token for the Surfsky.io service.
- **NUM_BROWSERS** (default: 1): Number of browser instances to run in parallel. Increase this value to improve throughput for large-scale scraping.
- **PROXIES**: A list of proxy URLs to use with the browsers. Each browser will be assigned a proxy from this list according to the PROXY_ORDERING strategy.
- **PAGES_PER_BROWSER** (default: 100): Maximum number of pages a browser instance will process before being recycled.
- **START_SEMAPHORES** (default: 10): Controls how many browsers can be started simultaneously. This prevents overwhelming the system with too many concurrent browser startups.
- **PROXY_ORDERING** (default: 'random'): Strategy for assigning proxies to browsers. Options are:
  - 'random': Randomly select a proxy from the list for each browser
  - 'round-robin': Cycle through the proxy list in order

For detailed browser settings (BROWSER_SETTINGS) and fingerprint configuration options (FINGERPRINT), please refer to the [Surfsky API Reference](https://docs.surfsky.io/api-reference).

Add cloud browser handlers and change reactor in `settings.py`:

```python
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

EXTENSIONS = {
    'scrapy_cloud_browser.CloudBrowserExtension': 100,
}
```

## License

`scrapy-cloud-browser` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
