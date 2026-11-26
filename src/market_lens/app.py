"""조립 지점: 설정, 캐시, HTTP 클라이언트, 소스 클라이언트를 한데 묶는다.

서비스 함수는 필요한 클라이언트를 인자로 받고, 여기서만 실제 객체를 만든다.
"""

from __future__ import annotations

import logging
from functools import cached_property

import httpx

from .cache import Cache
from .config import Settings, load_settings
from .errors import MissingKeyError
from .sources.dart import DartClient
from .sources.fsc import FscClient

# httpx는 INFO 수준에서 요청 URL을 통째로 남기는데, 거기에 API 키가 쿼리로 들어 있다.
logging.getLogger("httpx").setLevel(logging.WARNING)


class App:
    """테스트에서는 http와 cache를 바꿔 넣고 set_app으로 끼운다."""

    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient | None = None,
        cache: Cache | None = None,
    ):
        """http와 cache를 생략하면 실제 HTTP 클라이언트와 설정된 경로의 SQLite 캐시를 쓴다."""
        self.settings = settings
        self.http = http or httpx.AsyncClient(timeout=20.0)
        self.cache = cache or Cache(settings.cache_path)

    @cached_property
    def dart(self) -> DartClient:
        """DART 클라이언트. 키가 없으면 발급 안내와 함께 MissingKeyError."""
        if not self.settings.dart_api_key:
            raise MissingKeyError("DART_API_KEY", "https://opendart.fss.or.kr")
        return DartClient(self.settings.dart_api_key, self.http, self.cache)

    @cached_property
    def fsc(self) -> FscClient:
        """공공데이터포털 클라이언트. 키가 없으면 발급 안내와 함께 MissingKeyError."""
        if not self.settings.data_go_kr_key:
            raise MissingKeyError("DATA_GO_KR_KEY", "https://www.data.go.kr")
        return FscClient(self.settings.data_go_kr_key, self.http, self.cache)

    @property
    def dart_or_none(self) -> DartClient | None:
        """DART 키가 있으면 클라이언트, 없으면 None. 키 없이도 동작하는 도구용."""
        return self.dart if self.settings.dart_api_key else None

    @property
    def fsc_or_none(self) -> FscClient | None:
        """공공데이터포털 키가 있으면 클라이언트, 없으면 None. 키 없이도 동작하는 도구용."""
        return self.fsc if self.settings.data_go_kr_key else None


_app: App | None = None


def get_app() -> App:
    """프로세스에서 함께 쓰는 App. 처음 불릴 때 환경변수와 .env를 읽어 만든다."""
    global _app
    if _app is None:
        _app = App(load_settings())
    return _app


def set_app(app: App | None) -> None:
    """함께 쓰는 App을 바꿔 끼운다(테스트용). None을 넘기면 다음 get_app이 새로 만든다."""
    global _app
    _app = app
