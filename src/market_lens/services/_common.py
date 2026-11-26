"""서비스 공통: 응답 형식 만들기, DART 회사 찾기."""

from __future__ import annotations

from typing import Any

from ..errors import NotFoundError
from ..models import Envelope
from ..sources._base import Fetched
from ..sources.dart import DartClient
from ..util import iso_kst


def citation(source: str, as_of: str) -> str:
    """답변에 그대로 옮겨 적을 인용 문구를 만든다.

    출처와 기준일을 모델이 직접 조합하게 두면 한쪽을 빠뜨리기 쉬워 완성된 문장으로 준다.

    Args:
        source: 데이터 출처 이름.
        as_of: 데이터 기준일 또는 기준 시각.

    Returns:
        '출처: … · 기준일: …' 형식의 문구.
    """
    return f"출처: {source} · 기준일: {as_of}"


def envelope(
    source: str,
    as_of: str,
    data: Any,
    *fetched: Fetched,
    computed: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """도구 응답을 공통 형식(models.Envelope)으로 만든다.

    Args:
        source: 데이터 출처 이름.
        as_of: 데이터 기준일 또는 기준 시각.
        data: 도구별 결과 모델.
        *fetched: 이 응답을 만드는 데 쓴 조회 결과들. 하나 이상 넘긴다.
        computed: 코드로 계산한 파생 수치.
        warnings: 주의 사항.

    Returns:
        Envelope를 dict로 바꾼 값. citation은 source와 as_of로 만들고, fetched_at은 조회 가운데 가장 이른 시각이고,
        cached는 모든 조회가 캐시였을 때만 True다.
    """
    return Envelope(
        source=source,
        as_of=as_of,
        citation=citation(source, as_of),
        fetched_at=iso_kst(min(f.fetched_at for f in fetched)),
        cached=all(f.cached for f in fetched),
        data=data,
        computed=computed,
        warnings=warnings or [],
    ).model_dump()


async def find_corp(dart: DartClient, ticker: str) -> dict[str, str]:
    """종목명이나 종목코드로 DART 회사를 찾는다.

    Args:
        dart: DART 클라이언트.
        ticker: 종목명 또는 6자리 종목코드.

    Returns:
        corp_code, corp_name, stock_code를 담은 dict.

    Raises:
        NotFoundError: 일치하는 상장사가 없을 때. 비슷한 회사가 있으면 메시지에 싣는다.
    """
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
