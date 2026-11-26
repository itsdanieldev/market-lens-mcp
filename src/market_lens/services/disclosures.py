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
    """'A' 같은 코드나 '정기공시' 같은 이름을 DART 공시유형 코드로 바꾼다."""
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
    """기간 안의 공시 목록을 최신순으로 돌려준다. 날짜를 생략하면 오늘까지 30일."""
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
    """공시 본문에서 offset부터 max_chars만큼 돌려준다. as_of는 접수일이다."""
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
