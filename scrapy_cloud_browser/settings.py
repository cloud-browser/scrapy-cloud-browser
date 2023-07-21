from collections.abc import Awaitable, Callable
from typing import Literal, Union, Optional

from pydantic import AnyUrl, BaseModel, ConfigDict, HttpUrl, PositiveInt, conlist, constr


class SettingsScheme(BaseModel):
    API_HOST: HttpUrl
    API_TOKEN: constr(min_length=1)
    NUM_BROWSERS: Optional[PositiveInt] = 1
    PROXIES: conlist(item_type=Union[AnyUrl, Callable[[None], Awaitable[AnyUrl]]], min_length=1)
    INIT_HANDLER: Optional[str] = None
    PAGES_PER_BROWSER: Optional[PositiveInt] = 100
    START_SEMAPHORES: Optional[PositiveInt] = 10
    PROXY_ORDERING: Optional[Literal['random', 'round-robin']] = 'random'

    model_config = ConfigDict(title='CLOUD_BROWSER')
