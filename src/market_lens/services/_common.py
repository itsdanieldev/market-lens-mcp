"""서비스 공통: 응답 형식 만들기, DART 회사 찾기."""

from __future__ import annotations

from typing import Any

from ..errors import NotFoundError
from ..models import Envelope
from ..sources._base import Fetched
from ..sources.dart import DartClient
from ..util import iso_kst


def envelope(
    source: str,
    as_of: str,
    data: Any,
    *fetched: Fetched,
    computed: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """모든 도구가 돌려주는 공통 형식. 여러 번 받아 왔으면 가장 이른 시각을 적는다."""
    return Envelope(
        source=source,
        as_of=as_of,
        fetched_at=iso_kst(min(f.fetched_at for f in fetched)),
        cached=all(f.cached for f in fetched),
        data=data,
        computed=computed,
        warnings=warnings or [],
    ).model_dump()


async def find_corp(dart: DartClient, ticker: str) -> dict[str, str]:
    """종목명/코드 → {corp_code, corp_name, stock_code}. 없으면 비슷한 회사를 알려 준다."""
    corp, candidates = await dart.find_corp(ticker)
    if corp:
        return corp
    hint = ""
    if candidates:
        names = ", ".join(f"{c['corp_name']}({c['stock_code']})" for c in candidates[:5])
        hint = f" 비슷한 상장사: {names}"
    raise NotFoundError(
        f"'{ticker}'에 해당하는 상장사를 찾지 못했습니다.{hint} "
        "resolve_ticker로 종목코드를 확인해 주세요."
    )
