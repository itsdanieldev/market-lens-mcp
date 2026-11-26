"""get_stock_prices: 일별 시세와 기간 요약."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from .. import analytics
from ..errors import InvalidInputError, NotFoundError
from ..models import PriceRow, Prices
from ..sources import fsc as fsc_api
from ..sources._base import Fetched
from ..util import clean_stock_code, is_stock_code, norm_name, now_kst, parse_date
from ._common import envelope

DEFAULT_DAYS = 90


async def _short_code(fsc: fsc_api.FscClient, ticker: str, fetched: list[Fetched]) -> str:
    """종목 입력을 6자리 단축코드로 바꾼다.

    Args:
        fsc: 공공데이터포털 클라이언트.
        ticker: 종목명 또는 종목코드. 코드는 조회 없이 그대로 쓴다.
        fetched: 종목 검색을 했을 때 그 조회 결과를 더해 넣을 목록.

    Returns:
        6자리 단축코드.

    Raises:
        NotFoundError: 이름이 정확히 같은 종목이 없을 때. 비슷한 종목이 있으면 메시지에 싣는다.
    """
    if is_stock_code(ticker):
        return clean_stock_code(ticker)
    items = await fsc.search_items(name=ticker.strip())
    fetched.append(items)
    exact = [i for i in items.value if norm_name(i["name"]) == norm_name(ticker)]
    if not exact:
        names = ", ".join(f"{i['name']}({i['short_code']})" for i in items.value[:5])
        raise NotFoundError(
            f"'{ticker}'와 이름이 정확히 같은 종목이 없습니다."
            + (f" 비슷한 종목: {names}" if names else "")
        )
    return exact[0]["short_code"]


async def get_stock_prices(
    fsc: fsc_api.FscClient, ticker: str, start_date: str | None, end_date: str | None
) -> dict[str, Any]:
    """기간 안의 일별 시세와 기간 요약을 돌려준다.

    Args:
        fsc: 공공데이터포털 클라이언트.
        ticker: 종목명 또는 6자리 종목코드.
        start_date: 시작일(YYYY-MM-DD). None이면 종료일 90일 전.
        end_date: 종료일(YYYY-MM-DD). None이면 오늘.

    Returns:
        Prices를 담은 공통 형식. as_of는 마지막 거래일이고, computed에
        기간 수익률 등 요약이 들어 있다. 시세가 없으면 computed는 None.

    Raises:
        InvalidInputError: 날짜 형식이 잘못됐거나 시작일이 종료일보다 늦을 때.
        NotFoundError: 이름이 정확히 같은 종목이 없을 때.
        SourceError: 공공데이터포털이 오류를 돌려줬을 때.
    """
    end = parse_date(end_date, default=now_kst().date())
    start = parse_date(start_date, default=end - timedelta(days=DEFAULT_DAYS))
    if start > end:
        raise InvalidInputError("start_date가 end_date보다 늦습니다.")
    fetched: list[Fetched] = []
    code = await _short_code(fsc, ticker, fetched)

    daily = await fsc.stock_prices(code, start, end)
    fetched.append(daily)
    # 소스가 준 행에는 종목 정보(name, isin, market)도 있어 시세 필드만 골라 담는다.
    rows = [PriceRow(**{field: r[field] for field in PriceRow.model_fields}) for r in daily.value]
    warnings = ["수정주가가 아닙니다. 기간 안에 액면분할·증자 등이 있으면 수익률이 왜곡됩니다."]
    if not rows:
        warnings.append("해당 기간에 시세 자료가 없습니다. 종목코드와 기간을 확인하세요.")
    # 종목명 등은 기간 중 바뀔 수 있어 가장 최근 거래일의 값을 쓴다.
    last = daily.value[-1] if daily.value else {}
    data = Prices(
        short_code=code,
        name=last.get("name"),
        isin=last.get("isin"),
        market=last.get("market"),
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        prices=rows,
    )
    summary = analytics.price_summary([r.model_dump() for r in rows])
    as_of = rows[-1].date if rows else end.isoformat()
    return envelope(
        fsc_api.SOURCE_PRICES, as_of, data, *fetched, computed=summary, warnings=warnings
    )
