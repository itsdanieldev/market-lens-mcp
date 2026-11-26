"""픽스처 응답을 돌려주는 가짜 전송 계층. 테스트는 키와 네트워크 없이 돈다."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx
import pytest

from market_lens.app import App, set_app
from market_lens.cache import Cache
from market_lens.config import Settings
from market_lens.sources import _base

FIXTURES = Path(__file__).parent / "fixtures"
DART_KEY = "test-dart-key"
FSC_KEY = "test-fsc-key"
# DART 보고서 코드 → 녹화본 (1분기, 반기, 3분기, 사업보고서)
FINANCIAL_FIXTURES = {
    "11013": "dart_financials_q1.json",
    "11012": "dart_financials_half.json",
    "11014": "dart_financials.json",
    "11011": "dart_financials_annual.json",
}


def zipped(name: str, content: bytes) -> bytes:
    """파일 하나를 담은 ZIP을 만든다.

    Args:
        name: ZIP 안의 파일 이름.
        content: 파일 내용.

    Returns:
        ZIP 바이트.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, content)
    return buffer.getvalue()


class FakeApi:
    """URL 경로별로 픽스처를 돌려주는 가짜 API.

    Attributes:
        calls: 받은 요청 목록.
        overrides: 경로 일부 → 응답. 여기에 넣은 응답이 픽스처보다 먼저다.
    """

    def __init__(self) -> None:
        """요청 기록과 응답 바꿔치기 목록을 빈 상태로 만든다."""
        self.calls: list[httpx.Request] = []
        self.overrides: dict[str, httpx.Response] = {}

    def count(self, fragment: str) -> int:
        """특정 경로로 온 요청 수를 센다.

        Args:
            fragment: 경로에 들어 있어야 할 문자열.

        Returns:
            해당하는 요청 수.
        """
        return sum(1 for request in self.calls if fragment in request.url.path)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """요청을 기록하고 응답을 고른다(httpx.MockTransport가 부른다).

        Args:
            request: 받은 요청.

        Returns:
            overrides에 맞는 응답, 없으면 경로에 맞는 픽스처, 그것도 없으면 404.
        """
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
            name = FINANCIAL_FIXTURES[params["reprt_code"]]
            return httpx.Response(200, content=(FIXTURES / name).read_bytes())
        if path.endswith("/getItemInfo_V2"):
            return httpx.Response(200, content=(FIXTURES / "fsc_items.json").read_bytes())
        if path.endswith("/getStockPriceInfo_V2"):
            return httpx.Response(200, content=(FIXTURES / "fsc_prices.json").read_bytes())
        return httpx.Response(404, text="not found")


@pytest.fixture
def api() -> FakeApi:
    """요청을 기록하고 픽스처로 답하는 가짜 API.

    Returns:
        새 FakeApi.
    """
    return FakeApi()


@pytest.fixture
def make_app(api, tmp_path, monkeypatch):
    """가짜 API와 메모리 캐시로 App을 만들어 끼우는 함수를 준다.

    Args:
        api: 가짜 API.
        tmp_path: 설정의 캐시 경로로 쓸 임시 폴더.
        monkeypatch: 재시도 대기 시간을 0으로 바꾸는 데 쓴다.

    Yields:
        App을 만드는 함수. 테스트가 끝나면 끼운 App을 뺀다.
    """
    monkeypatch.setattr(_base, "RETRY_DELAY", 0)
    created = []

    def factory(dart_key: str | None = DART_KEY, fsc_key: str | None = FSC_KEY) -> App:
        """주어진 키로 App을 만들어 전역으로 끼운다.

        Args:
            dart_key: DART 키. None이면 키가 없는 상태.
            fsc_key: 공공데이터포털 키. None이면 키가 없는 상태.

        Returns:
            만든 App.
        """
        settings = Settings(dart_key, fsc_key, tmp_path / "cache.sqlite3")
        app = App(
            settings,
            http=httpx.AsyncClient(transport=httpx.MockTransport(api)),
            cache=Cache(":memory:"),
        )
        set_app(app)
        created.append(app)
        return app

    yield factory
    set_app(None)


@pytest.fixture
def app(make_app) -> App:
    """두 키가 모두 있는 기본 App.

    Args:
        make_app: App을 만드는 함수.

    Returns:
        만든 App.
    """
    return make_app()
