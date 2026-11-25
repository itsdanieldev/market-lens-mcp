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
    value: Any
    fetched_at: float  # epoch 초. 캐시된 값이면 처음 받아 온 시각
    cached: bool


class BaseSource:
    name = "source"

    def __init__(self, api_key: str, http: httpx.AsyncClient, cache: Cache):
        self._key = api_key
        self._http = http
        self._cache = cache

    async def _get(self, url: str, params: dict[str, Any]) -> httpx.Response:
        """GET. 네트워크 오류와 5xx는 재시도한다. 예외에 URL(키 포함)을 싣지 않는다."""
        last = "알 수 없는 오류"
        for attempt in range(RETRIES):
            try:
                response = await self._http.get(url, params=params)
            except httpx.TransportError as exc:
                last = f"네트워크 오류({type(exc).__name__})"
            else:
                if response.status_code < 500:
                    return response
                last = f"HTTP {response.status_code}"
            if attempt < RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * 2**attempt)
        raise SourceError(f"{self.name} 요청 실패: {last}")

    async def _cached(self, key: str, ttl: float, loader: Callable[[], Awaitable[Any]]) -> Fetched:
        hit = self._cache.get(key)
        if hit is not None:
            return Fetched(hit.value, hit.stored_at, True)
        value = await loader()
        self._cache.set(key, value, ttl)
        return Fetched(value, self._cache.now(), False)
