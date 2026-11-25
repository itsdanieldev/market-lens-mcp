"""픽스처 응답을 돌려주는 가짜 전송 계층. 테스트는 키와 네트워크 없이 돈다."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx
import pytest

from kr_invest import server
from kr_invest.cache import Cache
from kr_invest.config import Settings
from kr_invest.sources import _base

FIXTURES = Path(__file__).parent / "fixtures"
DART_KEY = "test-dart-key"
FSC_KEY = "test-fsc-key"


def zipped(name: str, content: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, content)
    return buffer.getvalue()


class FakeApi:
    """URL 경로별로 픽스처를 돌려준다. overrides로 특정 경로의 응답을 바꾼다."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.overrides: dict[str, httpx.Response] = {}

    def count(self, fragment: str) -> int:
        return sum(1 for request in self.calls if fragment in request.url.path)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        for fragment, response in self.overrides.items():
            if fragment in path:
                return response
        params = request.url.params
        if path.endswith("/corpCode.xml"):
            body = zipped("CORPCODE.xml", (FIXTURES / "dart_corpcode.xml").read_bytes())
            return httpx.Response(200, content=body)
        if path.endswith("/list.json"):
            return httpx.Response(200, content=(FIXTURES / "dart_list.json").read_bytes())
        if path.endswith("/document.xml"):
            name = f"{params['rcept_no']}.xml"
            body = zipped(name, (FIXTURES / "dart_document.xml").read_bytes())
            return httpx.Response(200, content=body)
        if path.endswith("/fnlttSinglAcnt.json"):
            return httpx.Response(200, content=(FIXTURES / "dart_financials.json").read_bytes())
        if path.endswith("/getItemInfo"):
            return httpx.Response(200, content=(FIXTURES / "fsc_items.json").read_bytes())
        if path.endswith("/getStockPriceInfo"):
            return httpx.Response(200, content=(FIXTURES / "fsc_prices.json").read_bytes())
        return httpx.Response(404, text="not found")


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def make_app(api, tmp_path, monkeypatch):
    monkeypatch.setattr(_base, "RETRY_DELAY", 0)
    created = []

    def factory(dart_key: str | None = DART_KEY, fsc_key: str | None = FSC_KEY) -> server.App:
        settings = Settings(dart_key, fsc_key, tmp_path / "cache.sqlite3")
        app = server.App(
            settings,
            http=httpx.AsyncClient(transport=httpx.MockTransport(api)),
            cache=Cache(":memory:"),
        )
        server.set_app(app)
        created.append(app)
        return app

    yield factory
    server.set_app(None)


@pytest.fixture
def app(make_app) -> server.App:
    return make_app()
