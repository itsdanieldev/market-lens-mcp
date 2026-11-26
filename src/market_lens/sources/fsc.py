"""공공데이터포털 금융위원회 API 클라이언트: 주식시세정보, KRX상장종목정보.

- 주식시세정보: https://www.data.go.kr/data/15094808/openapi.do
- KRX상장종목정보: https://www.data.go.kr/data/15094775/openapi.do
두 API 모두 V2 주소를 쓴다(서비스 이름과 기능 이름 끝에 _V2). 옛 주소(/service/...)로 부르면
키가 맞아도 HTTP 403 SERVICE_KEY_IS_NOT_REGISTERED_ERROR가 돌아온다.
시세는 전 영업일 종가 기준으로 하루 늦게(영업일 다음 날 오후 1시 이후) 갱신된다.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from ..cache import TTL_REFERENCE, seconds_until_kst_midnight
from ..errors import SourceError
from ..util import clean_stock_code, now_kst, to_float, to_int, ymd, ymd_to_iso
from ._base import BaseSource, Fetched

BASE_URL = "https://apis.data.go.kr/1160100"
PRICE_URL = f"{BASE_URL}/GetStockSecuritiesInfoService_V2/getStockPriceInfo_V2"
ITEM_URL = f"{BASE_URL}/GetKrxListedInfoService_V2/getItemInfo_V2"
SOURCE_PRICES = "공공데이터포털 금융위원회_주식시세정보"
SOURCE_ITEMS = "공공데이터포털 금융위원회_KRX상장종목정보"

PAGE_SIZE = 1000
MAX_PAGES = 10
ITEM_LOOKBACK_DAYS = 10  # 연휴를 넘겨도 최근 기준일이 잡히도록


def _item(row: dict[str, Any]) -> dict[str, str]:
    """getItemInfo_V2의 한 행을 종목 한 줄로 바꾼다.

    Args:
        row: 원본 행. 단축코드는 'A005930'처럼 접두 문자가 붙어 온다.

    Returns:
        short_code(6자리), isin, name, market, corp_name, base_date(YYYYMMDD)를 담은 dict.
    """
    return {
        "short_code": clean_stock_code(row.get("srtnCd", "")),
        "isin": row.get("isinCd", ""),
        "name": row.get("itmsNm", ""),
        "market": row.get("mrktCtg", ""),
        "corp_name": row.get("corpNm", ""),
        "base_date": row.get("basDt", ""),
    }


def _price(row: dict[str, Any]) -> dict[str, Any]:
    """getStockPriceInfo_V2의 한 행을 일별 시세 한 줄로 바꾼다.

    Args:
        row: 원본 행. 숫자는 문자열로 온다.

    Returns:
        models.PriceRow의 필드와 종목 정보(name, isin, market)를 담은 dict.
    """
    return {
        "date": ymd_to_iso(row["basDt"]),
        "open": to_int(row.get("mkp")) or 0,
        "high": to_int(row.get("hipr")) or 0,
        "low": to_int(row.get("lopr")) or 0,
        "close": to_int(row.get("clpr")) or 0,
        "volume": to_int(row.get("trqu")) or 0,
        "trading_value": to_int(row.get("trPrc")),
        "change": to_int(row.get("vs")),
        "change_pct": to_float(row.get("fltRt")),
        "market_cap": to_int(row.get("mrktTotAmt")),
        "name": row.get("itmsNm"),
        "isin": row.get("isinCd"),
        "market": row.get("mrktCtg"),
    }


class FscClient(BaseSource):
    """공공데이터포털 금융위원회 API 클라이언트. 응답은 캐시하고 원본 필드는 정규화해서 돌려준다."""

    name = "공공데이터포털"

    async def search_items(self, *, name: str | None = None, code: str | None = None) -> Fetched:
        """상장종목을 검색한다(1일 캐시).

        Args:
            name: 종목명의 일부. code를 주지 않을 때 쓴다.
            code: 단축코드. 주면 name 대신 코드로 찾는다.

        Returns:
            값이 종목 목록(_item 형식)인 Fetched. 종목마다 최신 기준일 한 건만 있고,
            이름이 짧은 순으로 정렬돼 있다.

        Raises:
            SourceError: 공공데이터포털이 오류를 돌려줬을 때.
        """

        async def load() -> list[dict[str, str]]:
            """최근 며칠 치 종목 행을 받아 종목별 최신 기준일 한 건만 남긴다.

            Returns:
                종목 목록.
            """
            params: dict[str, Any] = {
                "beginBasDt": ymd(now_kst().date() - timedelta(days=ITEM_LOOKBACK_DAYS))
            }
            if code:
                params["likeSrtnCd"] = code
            else:
                params["likeItmsNm"] = name
            latest: dict[str, dict[str, str]] = {}
            for row in await self._fetch_all(ITEM_URL, params):
                item = _item(row)
                # 같은 종목이 기준일마다 한 줄씩 오므로 가장 최근 기준일만 남긴다.
                seen = latest.get(item["short_code"])
                if seen is None or item["base_date"] > seen["base_date"]:
                    latest[item["short_code"]] = item
            # 이름이 짧은 종목을 앞에 둔다. '삼성전자'로 찾으면 '삼성전자'가 먼저 온다.
            return sorted(latest.values(), key=lambda i: (len(i["name"]), i["short_code"]))

        key = f"fsc:items:{'code' if code else 'name'}:{code or name}"
        return await self._cached(key, TTL_REFERENCE, load)

    async def stock_prices(self, code: str, begin: date, end: date) -> Fetched:
        """일별 시세를 받는다(KST 자정까지 캐시).

        Args:
            code: 6자리 단축코드.
            begin: 시작일(포함).
            end: 종료일(포함).

        Returns:
            값이 일별 시세 목록(_price 형식, 날짜 오름차순)인 Fetched.

        Raises:
            SourceError: 공공데이터포털이 오류를 돌려줬을 때.
        """

        async def load() -> list[dict[str, Any]]:
            """기간 안의 원본 시세 행을 받아 코드가 정확히 같은 행만 날짜순으로 남긴다.

            Returns:
                원본 행 목록.
            """
            params = {
                "likeSrtnCd": code,
                "beginBasDt": ymd(begin),
                # endBasDt는 '검색값보다 작은' 조건이라 하루를 더해 종료일을 포함시킨다.
                "endBasDt": ymd(end + timedelta(days=1)),
            }
            # likeSrtnCd는 부분 일치라 코드가 더 긴 다른 종목이 섞일 수 있어 정확히 같은 행만 쓴다.
            rows = [r for r in await self._fetch_all(PRICE_URL, params) if r.get("srtnCd") == code]
            return sorted(rows, key=lambda r: r.get("basDt", ""))

        key = f"fsc:prices:{code}:{ymd(begin)}:{ymd(end)}"
        rows = await self._cached(key, seconds_until_kst_midnight(self._cache.now()), load)
        return rows.map(lambda v: [_price(row) for row in v])

    async def _fetch_all(self, url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """전체 건수를 채울 때까지 페이지를 넘기며 받는다.

        Args:
            url: API 주소.
            params: 검색 조건. 인증키, 결과 형식, 페이지 정보는 여기서 붙인다.

        Returns:
            원본 행 목록. 최대 MAX_PAGES쪽까지만 받는다.

        Raises:
            SourceError: 공공데이터포털이 오류를 돌려줬을 때.
        """
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
            # 빈 쪽이 오거나 전체 건수를 다 받았으면 멈춘다.
            if not items or len(rows) >= total:
                break
        return rows


def _parse(response: Any) -> tuple[list[dict[str, Any]], int]:
    """응답에서 행 목록과 전체 건수를 꺼낸다.

    Args:
        response: HTTP 응답.

    Returns:
        (원본 행 목록, 전체 건수). 결과가 없으면 빈 목록.

    Raises:
        SourceError: 키 오류처럼 형식이 다른 응답이거나 결과코드가 '00'이 아닐 때.
    """
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
    # 결과가 없을 때 items가 dict가 아닌 값(빈 문자열 등)으로 올 수 있어 방어적으로 읽는다.
    items = body.get("items") or {}
    item = items.get("item") if isinstance(items, dict) else None
    # XML을 JSON으로 바꾼 응답은 한 건일 때 목록이 아니라 dict 하나로 올 수 있다.
    if isinstance(item, dict):
        item = [item]
    return item or [], int(body.get("totalCount") or 0)
