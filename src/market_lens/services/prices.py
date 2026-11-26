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
    """종목코드는 그대로 쓰고, 종목명은 이름이 정확히 같은 상장 종목의 코드로 바꾼다."""
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
    end = parse_date(end_date, default=now_kst().date())
    start = parse_date(start_date, default=end - timedelta(days=DEFAULT_DAYS))
    if start > end:
        raise InvalidInputError("start_date가 end_date보다 늦습니다.")
    fetched: list[Fetched] = []
    code = await _short_code(fsc, ticker, fetched)

    daily = await fsc.stock_prices(code, start, end)
    fetched.append(daily)
    rows = [PriceRow(**{field: r[field] for field in PriceRow.model_fields}) for r in daily.value]
    warnings = ["수정주가가 아닙니다. 기간 안에 액면분할·증자 등이 있으면 수익률이 왜곡됩니다."]
    if not rows:
        warnings.append("해당 기간에 시세 자료가 없습니다. 종목코드와 기간을 확인하세요.")
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
