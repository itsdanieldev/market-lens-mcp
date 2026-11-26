"""list_disclosures, get_disclosure_text: DART 공시 목록과 본문."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from ..errors import InvalidInputError
from ..models import Disclosure, DisclosureList, DisclosureText
from ..sources import dart as dart_api
from ..util import iso_kst, norm_name, now_kst, parse_date, ymd, ymd_to_iso
from ._common import envelope, find_corp

DEFAULT_DAYS = 30


def disclosure_kind(value: str | None) -> str | None:
    """공시유형 입력을 DART 공시유형 코드로 바꾼다.

    Args:
        value: 'A' 같은 코드 또는 '정기공시' 같은 이름.

    Returns:
        A~J 가운데 한 글자. 입력이 비어 있으면 None.

    Raises:
        InvalidInputError: 알 수 없는 유형일 때.
    """
    if value is None or not value.strip():
        return None
    text = value.strip()
    if text.upper() in dart_api.DISCLOSURE_TYPES:
        return text.upper()
    for code, name in dart_api.DISCLOSURE_TYPES.items():
        if norm_name(name) == norm_name(text):
            return code
    raise InvalidInputError(
        f"알 수 없는 공시유형: {value!r}. A~J 코드 또는 '정기공시' 같은 이름을 쓰세요."
    )


async def list_disclosures(
    dart: dart_api.DartClient,
    ticker: str,
    start_date: str | None,
    end_date: str | None,
    disclosure_type: str | None,
    limit: int,
) -> dict[str, Any]:
    """기간 안의 공시 목록을 최신순으로 돌려준다.

    Args:
        dart: DART 클라이언트.
        ticker: 종목명 또는 6자리 종목코드.
        start_date: 시작일(YYYY-MM-DD). None이면 종료일 30일 전.
        end_date: 종료일(YYYY-MM-DD). None이면 오늘.
        disclosure_type: 공시유형 코드 또는 이름. None이면 전체.
        limit: 최대 건수.

    Returns:
        DisclosureList를 담은 공통 형식. as_of는 목록을 받아 온 시각이고,
        computed에 returned_count와 has_more가 들어 있다.

    Raises:
        InvalidInputError: 날짜 형식이나 공시유형이 잘못됐거나 시작일이 종료일보다 늦을 때.
        NotFoundError: 일치하는 상장사가 없을 때.
        SourceError: DART가 오류를 돌려줬을 때.
    """
    end = parse_date(end_date, default=now_kst().date())
    start = parse_date(start_date, default=end - timedelta(days=DEFAULT_DAYS))
    if start > end:
        raise InvalidInputError("start_date가 end_date보다 늦습니다.")
    kind = disclosure_kind(disclosure_type)
    corp = await find_corp(dart, ticker)
    listing = await dart.list_disclosures(corp["corp_code"], ymd(start), ymd(end), kind, limit)
    disclosures = [Disclosure(**item) for item in listing.value["items"]]
    data = DisclosureList(
        corp_code=corp["corp_code"],
        corp_name=corp["corp_name"],
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        disclosure_type=dart_api.DISCLOSURE_TYPES[kind] if kind else None,
        total_count=listing.value["total_count"],
        disclosures=disclosures,
    )
    computed = {
        "returned_count": len(disclosures),
        "has_more": listing.value["total_count"] > len(disclosures),
    }
    return envelope(dart_api.SOURCE, iso_kst(listing.fetched_at), data, listing, computed=computed)


async def disclosure_text(
    dart: dart_api.DartClient, rcept_no: str, max_chars: int, offset: int
) -> dict[str, Any]:
    """공시 본문의 일부를 돌려준다.

    Args:
        dart: DART 클라이언트.
        rcept_no: 접수번호(숫자 14자리).
        max_chars: 돌려줄 최대 글자 수.
        offset: 시작 위치(글자).

    Returns:
        DisclosureText를 담은 공통 형식. as_of는 접수일이다.

    Raises:
        InvalidInputError: 접수번호가 숫자 14자리가 아닐 때.
        NotFoundError: 해당 접수번호의 원문이 없을 때.
        SourceError: DART가 오류를 돌려줬을 때.
    """
    rcept_no = rcept_no.strip()
    if not re.fullmatch(r"\d{14}", rcept_no):
        raise InvalidInputError("rcept_no는 숫자 14자리여야 합니다.")
    doc = await dart.document_text(rcept_no)
    full: str = doc.value
    chunk = full[offset : offset + max_chars]
    end = offset + len(chunk)
    data = DisclosureText(
        rcept_no=rcept_no,
        url=dart_api.VIEWER_URL.format(rcept_no=rcept_no),
        total_chars=len(full),
        offset=offset,
        returned_chars=len(chunk),
        truncated=end < len(full),
        next_offset=end if end < len(full) else None,
        text=chunk,
    )
    # 접수번호 앞 8자리가 접수일이다.
    return envelope(dart_api.SOURCE, ymd_to_iso(rcept_no[:8]), data, doc)
