"""resolve_ticker: 종목명·코드를 단축코드, ISIN, DART corp_code, 시장으로 바꾼다."""

from __future__ import annotations

from typing import Any

from ..errors import InvalidInputError, MissingKeyError, SourceError
from ..models import Ticker, TickerResult
from ..sources import dart as dart_api
from ..sources import fsc as fsc_api
from ..sources._base import Fetched
from ..util import clean_stock_code, is_stock_code, norm_name, now_kst, ymd_to_iso
from ._common import envelope


async def resolve(
    query: str, *, dart: dart_api.DartClient | None, fsc: fsc_api.FscClient | None
) -> dict[str, Any]:
    """키가 있는 소스만 넘겨받는다. 한쪽만 있으면 그쪽에서 오는 항목만 채운다."""
    query = query.strip()
    if not query:
        raise InvalidInputError("query가 비어 있습니다.")
    if dart is None and fsc is None:
        raise MissingKeyError("DATA_GO_KR_KEY", "https://www.data.go.kr")
    warnings: list[str] = []
    fetched: list[Fetched] = []
    sources: list[str] = []
    tickers: list[Ticker] = []
    as_of = now_kst().date().isoformat()

    corp_by_stock: dict[str, dict[str, str]] = {}
    if dart is not None:
        index = await dart.corp_index()
        fetched.append(index)
        sources.append(dart_api.SOURCE)
        corp_by_stock = {c["stock_code"]: c for c in index.value}
    else:
        warnings.append("DART_API_KEY가 없어 corp_code를 채우지 못했습니다.")

    items: Fetched | None = None
    if fsc is not None:
        try:
            if is_stock_code(query):
                items = await fsc.search_items(code=clean_stock_code(query))
            else:
                items = await fsc.search_items(name=query)
        except SourceError as exc:
            # 포털 장애나 해외 IP 차단 때도 DART만으로 종목은 확인해 준다.
            if dart is None:
                raise
            warnings.append(
                f"공공데이터포털 조회에 실패해 ISIN과 시장 구분을 채우지 못했습니다({exc})"
            )
    else:
        warnings.append("DATA_GO_KR_KEY가 없어 ISIN과 시장 구분을 채우지 못했습니다.")

    if items is not None:
        fetched.append(items)
        sources.insert(0, fsc_api.SOURCE_ITEMS)
        for item in items.value:
            corp = corp_by_stock.get(item["short_code"])
            tickers.append(
                Ticker(
                    short_code=item["short_code"],
                    name=item["name"],
                    isin=item["isin"] or None,
                    corp_code=corp["corp_code"] if corp else None,
                    market=item["market"] or None,
                )
            )
        if items.value:
            as_of = ymd_to_iso(max(i["base_date"] for i in items.value))
    else:
        corp, candidates = await dart.find_corp(query)
        for c in [corp] if corp else candidates:
            tickers.append(
                Ticker(short_code=c["stock_code"], name=c["corp_name"], corp_code=c["corp_code"])
            )

    if is_stock_code(query):
        exact = [t for t in tickers if t.short_code == clean_stock_code(query)]
    else:
        exact = [t for t in tickers if norm_name(t.name) == norm_name(query)]
    match = exact[0] if exact else (tickers[0] if len(tickers) == 1 else None)
    if match is None and not tickers:
        warnings.append("일치하는 상장 종목이 없습니다.")
    if match and match.corp_code is None and dart is not None:
        warnings.append("이 종목코드에 연결된 DART 고유번호가 없습니다(우선주, ETF 등).")

    result = TickerResult(
        query=query,
        match=match,
        candidates=[] if match and len(tickers) == 1 else tickers[:10],
    )
    return envelope(" + ".join(sources), as_of, result, *fetched, warnings=warnings)
