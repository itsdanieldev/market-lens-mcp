"""소스 클라이언트 공통: 재시도, 캐시, 키가 새지 않는 오류 메시지."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from ..cache import Cache
from ..errors import SourceError

RETRIES = 3
RETRY_DELAY = 0.5  # 초. 시도마다 두 배


@dataclass(frozen=True)
class Fetched:
    """소스에서 받은 값과 그 출처 정보.

    Attributes:
        value: 받은 값.
        fetched_at: 받아 온 시각(epoch 초). 캐시된 값이면 처음 받아 온 시각.
        cached: 캐시에서 읽었는지 여부.
    """

    value: Any
    fetched_at: float  # epoch 초. 캐시된 값이면 처음 받아 온 시각
    cached: bool

    def map(self, convert: Callable[[Any], Any]) -> Fetched:
        """값만 바꾼 새 Fetched를 만든다.

        Args:
            convert: 값을 바꾸는 함수.

        Returns:
            바뀐 값을 담은 Fetched. 받아 온 시각과 캐시 여부는 그대로다.
        """
        return Fetched(convert(self.value), self.fetched_at, self.cached)


class BaseSource:
    """소스 클라이언트의 공통 부모.

    하위 클래스는 name을 정하고 _get, _cached로 API를 부른다.

    Attributes:
        name: 오류 메시지에 쓰는 소스 이름.
    """

    name = "source"

    def __init__(self, api_key: str, http: httpx.AsyncClient, cache: Cache):
        """클라이언트를 만든다.

        Args:
            api_key: 인증키. 요청 파라미터로만 쓴다.
            http: HTTP 클라이언트.
            cache: 응답을 저장할 캐시.
        """
        self._key = api_key
        self._http = http
        self._cache = cache

    async def _get(self, url: str, params: dict[str, Any]) -> httpx.Response:
        """GET 요청을 보낸다. 네트워크 오류와 5xx는 RETRIES번까지 다시 시도한다.

        Args:
            url: 요청 주소.
            params: 쿼리 파라미터(인증키 포함).

        Returns:
            상태 코드가 500 미만인 응답. 4xx도 그대로 돌려주므로 호출한 쪽에서 해석한다.

        Raises:
            SourceError: 끝까지 실패했을 때. 메시지에 URL(키 포함)은 싣지 않는다.
        """
        last = "알 수 없는 오류"
        for attempt in range(RETRIES):
            try:
                response = await self._http.get(url, params=params)
            except httpx.TransportError as exc:
                last = f"네트워크 오류({type(exc).__name__})"
            else:
                # 4xx는 다시 보내도 같으므로 바로 돌려주고, 사유 해석은 소스별 클라이언트가 한다.
                if response.status_code < 500:
                    return response
                last = f"HTTP {response.status_code}"
            if attempt < RETRIES - 1:
                # 0.5초, 1초로 간격을 늘려 다시 시도한다. 마지막 시도 뒤에는 기다리지 않는다.
                await asyncio.sleep(RETRY_DELAY * 2**attempt)
        raise SourceError(f"{self.name} 요청 실패: {last}")

    async def _cached(
        self,
        key: str,
        ttl: float,
        loader: Callable[[], Awaitable[Any]],
        *,
        keep: Callable[[Any], bool] = lambda value: True,
    ) -> Fetched:
        """캐시에 있으면 그 값을, 없으면 받아 와서 저장하고 돌려준다.

        Args:
            key: 캐시 키.
            ttl: 유효 기간(초).
            loader: 값을 받아 오는 함수.
            keep: 받아 온 값을 저장할지 정하는 함수. False를 돌려주면 저장하지 않는다.

        Returns:
            값과 받아 온 시각, 캐시 여부.
        """
        hit = self._cache.get(key)
        if hit is not None:
            return Fetched(hit.value, hit.stored_at, True)
        value = await loader()
        if keep(value):
            self._cache.set(key, value, ttl)
        return Fetched(value, self._cache.now(), False)
