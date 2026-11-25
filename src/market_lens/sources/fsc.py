"""공공데이터포털 금융위원회 API 클라이언트: 주식시세정보, KRX상장종목정보.

- 주식시세정보: https://www.data.go.kr/data/15094808/openapi.do
- KRX상장종목정보: https://www.data.go.kr/data/15094775/openapi.do
시세는 전 영업일 종가 기준으로 하루 늦게 갱신된다.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from ..cache import TTL_REFERENCE, seconds_until_kst_midnight
from ..errors import SourceError
from ..util import now_kst, ymd
from ._base import BaseSource, Fetched

BASE_URL = "https://apis.data.go.kr/1160100/service"
PRICE_URL = f"{BASE_URL}/GetStockSecuritiesInfoService/getStockPriceInfo"
ITEM_URL = f"{BASE_URL}/GetKrxListedInfoService/getItemInfo"
SOURCE_PRICES = "공공데이터포털 금융위원회_주식시세정보"
SOURCE_ITEMS = "공공데이터포털 금융위원회_KRX상장종목정보"

PAGE_SIZE = 1000
MAX_PAGES = 10
ITEM_LOOKBACK_DAYS = 10  # 연휴를 넘겨도 최근 기준일이 잡히도록


def strip_code(srtn_cd: str) -> str:
    """상장종목정보의 단축코드는 'A005930'처럼 접두 문자가 붙는다."""
    code = (srtn_cd or "").strip()
    return code[1:] if len(code) == 7 and code[0].isalpha() else code


class FscClient(BaseSource):
    name = "공공데이터포털"

    async def search_items(self, *, name: str | None = None, code: str | None = None) -> Fetched:
        """상장종목 검색(이름 부분 일치 또는 단축코드). 종목별 최신 기준일 한 건씩 돌려준다."""

        async def load() -> list[dict[str, str]]:
            params: dict[str, Any] = {
                "beginBasDt": ymd(now_kst().date() - timedelta(days=ITEM_LOOKBACK_DAYS))
            }
            if code:
                params["likeSrtnCd"] = code
            else:
                params["likeItmsNm"] = name
            latest: dict[str, dict[str, str]] = {}
            for row in await self._fetch_all(ITEM_URL, params):
                item = {
                    "short_code": strip_code(row.get("srtnCd", "")),
                    "isin": row.get("isinCd", ""),
                    "name": row.get("itmsNm", ""),
                    "market": row.get("mrktCtg", ""),
                    "corp_name": row.get("corpNm", ""),
                    "base_date": row.get("basDt", ""),
                }
                seen = latest.get(item["short_code"])
                if seen is None or item["base_date"] > seen["base_date"]:
                    latest[item["short_code"]] = item
            return sorted(latest.values(), key=lambda i: (len(i["name"]), i["short_code"]))

        key = f"fsc:items:{'code' if code else 'name'}:{code or name}"
        return await self._cached(key, TTL_REFERENCE, load)

    async def stock_prices(self, code: str, begin: date, end: date) -> Fetched:
        """일별 시세 원본 행(날짜 오름차순). begin, end 모두 포함."""

        async def load() -> list[dict[str, Any]]:
            params = {
                "likeSrtnCd": code,
                "beginBasDt": ymd(begin),
                # endBasDt는 '검색값보다 작은' 조건이라 하루를 더해 종료일을 포함시킨다.
                "endBasDt": ymd(end + timedelta(days=1)),
            }
            rows = [r for r in await self._fetch_all(PRICE_URL, params) if r.get("srtnCd") == code]
            return sorted(rows, key=lambda r: r.get("basDt", ""))

        key = f"fsc:prices:{code}:{ymd(begin)}:{ymd(end)}"
        return await self._cached(key, seconds_until_kst_midnight(self._cache.now()), load)

    async def _fetch_all(self, url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            query = {
                "serviceKey": self._key,
                "resultType": "json",
                "numOfRows": PAGE_SIZE,
                "pageNo": page,
                **params,
            }
            items, total = _parse(await self._get(url, query))
            rows.extend(items)
            if not items or len(rows) >= total:
                break
        return rows


def _parse(response: Any) -> tuple[list[dict[str, Any]], int]:
    try:
        payload = response.json()
        header = payload["response"]["header"]
        body = payload["response"]["body"]
    except (ValueError, KeyError, TypeError):
        # 키 오류 등은 형식이 다르다. XML로 올 때도 있고, 실제로 받아 보면 HTTP 403에
        # {"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"errMsg": ...}}} JSON으로 오기도 한다.
        text = response.text
        reason = (
            re.search(r"<returnAuthMsg>(.*?)</returnAuthMsg>", text)
            or re.search(r"<errMsg>(.*?)</errMsg>", text)
            or re.search(r'"errMsg"\s*:\s*"(.*?)"', text)
        )
        detail = reason.group(1) if reason else f"HTTP {response.status_code}"
        raise SourceError(
            f"공공데이터포털 오류: {detail}. 키가 맞는지, 해당 API 활용신청이 승인됐는지 확인하세요."
        ) from None
    if header.get("resultCode") != "00":
        raise SourceError(
            f"공공데이터포털 오류 {header.get('resultCode')}: {header.get('resultMsg')}"
        )
    items = body.get("items") or {}
    item = items.get("item") if isinstance(items, dict) else None
    if isinstance(item, dict):
        item = [item]
    return item or [], int(body.get("totalCount") or 0)
