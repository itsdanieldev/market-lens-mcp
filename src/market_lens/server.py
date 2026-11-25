"""market-lens MCP 서버: 한국 주식 리서치 도구 5개.

모든 도구는 source, as_of가 붙은 공통 형식(models.Envelope)으로 응답한다.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Annotated, Any

import httpx
from mcp.server.mcpserver import MCPServer
from pydantic import Field

from . import __version__, analytics
from .cache import Cache
from .config import Settings, load_settings
from .errors import InvalidInputError, MissingKeyError, NotFoundError, SourceError
from .models import (
    Account,
    Disclosure,
    DisclosureList,
    DisclosureText,
    Envelope,
    Financials,
    PriceRow,
    Prices,
    Ticker,
    TickerResult,
)
from .sources import dart as dart_api
from .sources import fsc as fsc_api
from .sources._base import Fetched
from .util import iso_kst, now_kst, parse_date, to_float, to_int, ymd, ymd_to_iso

INSTRUCTIONS = """\
한국 상장사의 공시, 재무제표, 주가를 공식 API(DART, 공공데이터포털 금융위원회)로 조회하는 \
리서치 도구입니다.

답변 규칙:
- 사실 정리와 설명만 합니다. 매수·매도 의견, 목표가, 종목 추천 같은 투자 권유 표현은 쓰지 않습니다.
- 답변의 숫자는 도구 응답 값만 인용합니다. 수익률·증감률은 직접 계산하지 말고 computed 필드를 씁니다.
- 답변 끝에 각 도구 응답의 source와 as_of를 출처·기준일로 밝힙니다.
- 주가는 전 영업일 종가 기준이며 실시간이 아닙니다.

종목 브리핑 순서 예: resolve_ticker → get_financials → list_disclosures →
(필요하면) get_disclosure_text → get_stock_prices.
"""

MAX_TEXT_CHARS = 50_000
REPORT_NAMES = {1: "1분기보고서", 2: "반기보고서", 3: "3분기보고서", 4: "사업보고서"}
# 응답 키 → DART 계정명 판별
ACCOUNT_MATCHERS = {
    "revenue": lambda n: n in ("매출액", "수익(매출액)", "영업수익"),
    "operating_income": lambda n: n.startswith("영업이익"),
    "net_income": lambda n: n.startswith(("당기순이익", "분기순이익", "반기순이익")),
    "total_assets": lambda n: n == "자산총계",
    "total_liabilities": lambda n: n == "부채총계",
    "total_equity": lambda n: n == "자본총계",
}

mcp = MCPServer("market-lens", instructions=INSTRUCTIONS, version=__version__)
# httpx는 INFO 수준에서 요청 URL을 통째로 남기는데, 거기에 API 키가 쿼리로 들어 있다.
logging.getLogger("httpx").setLevel(logging.WARNING)


class App:
    """설정, 캐시, HTTP 클라이언트, 소스 클라이언트 묶음. 테스트에서는 set_app으로 바꿔 끼운다."""

    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient | None = None,
        cache: Cache | None = None,
    ):
        self.settings = settings
        self.http = http or httpx.AsyncClient(timeout=20.0)
        self.cache = cache or Cache(settings.cache_path)

    @property
    def dart(self) -> dart_api.DartClient:
        if not self.settings.dart_api_key:
            raise MissingKeyError("DART_API_KEY", "https://opendart.fss.or.kr")
        return dart_api.DartClient(self.settings.dart_api_key, self.http, self.cache)

    @property
    def fsc(self) -> fsc_api.FscClient:
        if not self.settings.data_go_kr_key:
            raise MissingKeyError("DATA_GO_KR_KEY", "https://www.data.go.kr")
        return fsc_api.FscClient(self.settings.data_go_kr_key, self.http, self.cache)


_app: App | None = None


def get_app() -> App:
    global _app
    if _app is None:
        _app = App(load_settings())
    return _app


def set_app(app: App | None) -> None:
    global _app
    _app = app


def _envelope(
    source: str,
    as_of: str,
    data: Any,
    *fetched: Fetched,
    computed: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return Envelope(
        source=source,
        as_of=as_of,
        fetched_at=iso_kst(min(f.fetched_at for f in fetched)),
        cached=all(f.cached for f in fetched),
        data=data,
        computed=computed,
        warnings=warnings or [],
    ).model_dump()


def _is_code(query: str) -> bool:
    return bool(re.fullmatch(r"[Aa]?\d[0-9A-Za-z]{5}", query.strip()))


def _clean_code(query: str) -> str:
    code = query.strip().upper()
    return code[1:] if len(code) == 7 else code


def _norm(name: str) -> str:
    return re.sub(r"\s+", "", name).casefold()


async def _find_corp(ticker: str) -> dict[str, str]:
    """DART 도구용: 종목명/코드 → {corp_code, corp_name, stock_code}."""
    corp, candidates = await get_app().dart.find_corp(ticker)
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


@mcp.tool()
async def resolve_ticker(
    query: Annotated[
        str, Field(description="종목명(예: 삼성전자) 또는 6자리 종목코드(예: 005930)")
    ],
) -> dict[str, Any]:
    """종목명이나 종목코드를 단축코드, ISIN, DART corp_code, 시장으로 바꾼다.

    하나로 확정되면 match에, 여러 개가 걸리면 candidates에 담는다.
    """
    app = get_app()
    query = query.strip()
    if not query:
        raise InvalidInputError("query가 비어 있습니다.")
    warnings: list[str] = []
    fetched: list[Fetched] = []
    sources: list[str] = []
    tickers: list[Ticker] = []
    as_of = now_kst().date().isoformat()

    corp_by_stock: dict[str, dict[str, str]] = {}
    if app.settings.dart_api_key:
        index = await app.dart.corp_index()
        fetched.append(index)
        sources.append(dart_api.SOURCE)
        corp_by_stock = {c["stock_code"]: c for c in index.value}
    else:
        warnings.append("DART_API_KEY가 없어 corp_code를 채우지 못했습니다.")

    items: Fetched | None = None
    if app.settings.data_go_kr_key:
        try:
            if _is_code(query):
                items = await app.fsc.search_items(code=_clean_code(query))
            else:
                items = await app.fsc.search_items(name=query)
        except SourceError as exc:
            # 포털 장애나 해외 IP 차단 때도 DART만으로 종목은 확인해 준다.
            if not app.settings.dart_api_key:
                raise
            warnings.append(
                f"공공데이터포털 조회에 실패해 ISIN과 시장 구분을 채우지 못했습니다({exc})"
            )
    elif app.settings.dart_api_key:
        warnings.append("DATA_GO_KR_KEY가 없어 ISIN과 시장 구분을 채우지 못했습니다.")
    else:
        raise MissingKeyError("DATA_GO_KR_KEY", "https://www.data.go.kr")

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
        corp, candidates = await app.dart.find_corp(query)
        for c in [corp] if corp else candidates:
            tickers.append(
                Ticker(short_code=c["stock_code"], name=c["corp_name"], corp_code=c["corp_code"])
            )

    if _is_code(query):
        exact = [t for t in tickers if t.short_code == _clean_code(query)]
    else:
        exact = [t for t in tickers if _norm(t.name) == _norm(query)]
    match = exact[0] if exact else (tickers[0] if len(tickers) == 1 else None)
    if match is None and not tickers:
        warnings.append("일치하는 상장 종목이 없습니다.")
    if match and match.corp_code is None and app.settings.dart_api_key:
        warnings.append("이 종목코드에 연결된 DART 고유번호가 없습니다(우선주, ETF 등).")

    result = TickerResult(
        query=query,
        match=match,
        candidates=[] if match and len(tickers) == 1 else tickers[:10],
    )
    return _envelope(" + ".join(sources), as_of, result, *fetched, warnings=warnings)


@mcp.tool()
async def list_disclosures(
    ticker: Annotated[str, Field(description="종목명 또는 6자리 종목코드")],
    start_date: Annotated[
        str | None, Field(description="시작일 YYYY-MM-DD. 생략하면 종료일 30일 전")
    ] = None,
    end_date: Annotated[str | None, Field(description="종료일 YYYY-MM-DD. 생략하면 오늘")] = None,
    disclosure_type: Annotated[
        str | None,
        Field(
            description="공시유형 코드 또는 이름: A 정기공시, B 주요사항보고, C 발행공시, D 지분공시, "
            "E 기타공시, F 외부감사관련, G 펀드공시, H 자산유동화, I 거래소공시, J 공정위공시"
        ),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=200, description="최대 건수")] = 30,
) -> dict[str, Any]:
    """기간 안의 DART 공시 목록을 최신순으로 돌려준다(제목, 접수일, 접수번호)."""
    end = parse_date(end_date, default=now_kst().date())
    start = parse_date(start_date, default=end - timedelta(days=30))
    if start > end:
        raise InvalidInputError("start_date가 end_date보다 늦습니다.")
    kind = _disclosure_kind(disclosure_type)
    corp = await _find_corp(ticker)
    listing = await get_app().dart.list_disclosures(
        corp["corp_code"], ymd(start), ymd(end), kind, limit
    )
    disclosures = [
        Disclosure(
            rcept_no=row["rcept_no"],
            title=(row.get("report_nm") or "").strip(),
            date=ymd_to_iso(row.get("rcept_dt", "")),
            filer=row.get("flr_nm", ""),
            corp_name=row.get("corp_name", ""),
            remark=row.get("rm", "") or "",
            url=dart_api.VIEWER_URL.format(rcept_no=row["rcept_no"]),
        )
        for row in listing.value["items"]
    ]
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
    return _envelope(dart_api.SOURCE, iso_kst(listing.fetched_at), data, listing, computed=computed)


def _disclosure_kind(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    text = value.strip()
    if text.upper() in dart_api.DISCLOSURE_TYPES:
        return text.upper()
    for code, name in dart_api.DISCLOSURE_TYPES.items():
        if _norm(name) == _norm(text):
            return code
    raise InvalidInputError(
        f"알 수 없는 공시유형: {value!r}. A~J 코드 또는 '정기공시' 같은 이름을 쓰세요."
    )


@mcp.tool()
async def get_disclosure_text(
    rcept_no: Annotated[str, Field(description="접수번호 14자리(list_disclosures의 rcept_no)")],
    max_chars: Annotated[
        int, Field(ge=500, le=MAX_TEXT_CHARS, description="돌려줄 최대 글자 수")
    ] = 8000,
    offset: Annotated[int, Field(ge=0, description="이어 읽을 시작 위치(글자)")] = 0,
) -> dict[str, Any]:
    """공시 원문의 본문 텍스트를 돌려준다. 길면 잘라서 주고 next_offset으로 이어 읽는다."""
    rcept_no = rcept_no.strip()
    if not re.fullmatch(r"\d{14}", rcept_no):
        raise InvalidInputError("rcept_no는 숫자 14자리여야 합니다.")
    doc = await get_app().dart.document_text(rcept_no)
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
    return _envelope(dart_api.SOURCE, ymd_to_iso(rcept_no[:8]), data, doc)


def _as_is(period: str | None) -> str | None:
    return period


def _three_months(period: str | None) -> str | None:
    """'2025.01.01 ~ 2025.09.30' 같은 누적 구간을 마지막 3개월 구간으로 바꾼다."""
    found = re.fullmatch(r"\s*\d{4}\.\d{2}\.\d{2}\s*~\s*((\d{4})\.(\d{2})\.\d{2})\s*", period or "")
    if not found:
        return period
    months = int(found.group(2)) * 12 + int(found.group(3)) - 3  # 0부터 센 시작 월
    return f"{months // 12}.{months % 12 + 1:02d}.01 ~ {found.group(1)}"


@mcp.tool()
async def get_financials(
    ticker: Annotated[str, Field(description="종목명 또는 6자리 종목코드")],
    year: Annotated[int, Field(ge=2015, description="사업연도(2015년 이후)")],
    quarter: Annotated[
        int, Field(ge=1, le=4, description="1~3은 해당 분기 보고서, 4는 사업보고서(연간 실적)")
    ] = 4,
) -> dict[str, Any]:
    """매출, 영업이익, 순이익, 자산, 부채, 자본과 증감률·이익률·부채비율을 돌려준다.

    금액 단위는 원. 연결재무제표가 있으면 연결, 없으면 별도 기준이다.
    분기(1~3)의 손익 항목 current는 3개월 금액이고 cumulative는 연초부터의 누적이다.
    quarter=4는 4분기 석 달이 아니라 연간 금액이다.
    """
    corp = await _find_corp(ticker)
    fetched = await get_app().dart.financials(corp["corp_code"], year, quarter)
    rows: list[dict[str, Any]] = fetched.value
    if not rows:
        raise NotFoundError(
            f"{corp['corp_name']} {year}년 {REPORT_NAMES[quarter]}의 재무 자료가 DART에 없습니다. "
            "아직 제출 전이거나 대상이 아닐 수 있습니다."
        )
    warnings: list[str] = []
    fs_div = "CFS" if any(r.get("fs_div") == "CFS" for r in rows) else "OFS"
    if fs_div == "OFS":
        warnings.append("연결재무제표가 없어 별도재무제표 기준입니다.")
    rows = [r for r in rows if r.get("fs_div") == fs_div]

    accounts: dict[str, Account | None] = {}
    for key, matches in ACCOUNT_MATCHERS.items():
        row = next((r for r in rows if matches(_norm(r.get("account_nm", "")))), None)
        if row is None:
            accounts[key] = None
            warnings.append(f"{key} 계정을 응답에서 찾지 못했습니다.")
            continue
        # 분기·반기 손익의 기간 표기는 누적 구간인데 금액은 3개월분이라 기간을 금액에 맞춘다.
        period = _three_months if quarter != 4 and row.get("sj_div") == "IS" else _as_is
        accounts[key] = Account(
            label=row.get("account_nm", ""),
            current=to_int(row.get("thstrm_amount")),
            current_period=period(row.get("thstrm_dt")),
            prior=to_int(row.get("frmtrm_amount")),
            prior_period=period(row.get("frmtrm_dt")),
            cumulative=to_int(row.get("thstrm_add_amount")),
            prior_cumulative=to_int(row.get("frmtrm_add_amount")),
        )

    def cur(key: str) -> int | None:
        return accounts[key].current if accounts[key] else None

    def prior(key: str) -> int | None:
        return accounts[key].prior if accounts[key] else None

    computed: dict[str, Any] = {
        "basis": "손익 증감률은 전년 동기 대비, 자산·부채·자본 증감률은 prior_period 시점 대비",
        "operating_margin_pct": analytics.ratio_pct(cur("operating_income"), cur("revenue")),
        "net_margin_pct": analytics.ratio_pct(cur("net_income"), cur("revenue")),
        "debt_to_equity_pct": analytics.ratio_pct(cur("total_liabilities"), cur("total_equity")),
    }
    for key, account in accounts.items():
        computed[f"{key}_change_pct"] = analytics.pct_change(cur(key), prior(key))
        if account and account.cumulative is not None:
            computed[f"{key}_cumulative_change_pct"] = analytics.pct_change(
                account.cumulative, account.prior_cumulative
            )
    if any(
        accounts[k] and accounts[k].prior is not None and accounts[k].prior <= 0 for k in accounts
    ):
        warnings.append("비교 금액이 0 이하인 계정은 증감률을 계산하지 않았습니다(null).")

    first = rows[0]
    periods = [a.current_period for a in accounts.values() if a and a.current_period]
    dates = re.findall(r"\d{4}\.\d{2}\.\d{2}", " ".join(periods))
    as_of = max(dates).replace(".", "-") if dates else f"{year}"
    data = Financials(
        corp_code=corp["corp_code"],
        corp_name=corp["corp_name"],
        year=year,
        quarter=quarter,
        report=REPORT_NAMES[quarter],
        period_type="annual" if quarter == 4 else "quarter",
        statement=first.get("fs_nm"),
        currency=first.get("currency"),
        rcept_no=first.get("rcept_no"),
        accounts=accounts,
    )
    return _envelope(dart_api.SOURCE, as_of, data, fetched, computed=computed, warnings=warnings)


@mcp.tool()
async def get_stock_prices(
    ticker: Annotated[str, Field(description="종목명 또는 6자리 종목코드")],
    start_date: Annotated[
        str | None, Field(description="시작일 YYYY-MM-DD. 생략하면 종료일 90일 전")
    ] = None,
    end_date: Annotated[str | None, Field(description="종료일 YYYY-MM-DD. 생략하면 오늘")] = None,
) -> dict[str, Any]:
    """일별 시가·고가·저가·종가·거래량(OHLCV)과 기간 수익률 요약을 돌려준다.

    전 영업일 종가까지 제공되며 실시간 시세가 아니다. 수정주가가 아니다.
    """
    app = get_app()
    end = parse_date(end_date, default=now_kst().date())
    start = parse_date(start_date, default=end - timedelta(days=90))
    if start > end:
        raise InvalidInputError("start_date가 end_date보다 늦습니다.")
    fetched: list[Fetched] = []
    if _is_code(ticker):
        code = _clean_code(ticker)
    else:
        items = await app.fsc.search_items(name=ticker.strip())
        fetched.append(items)
        exact = [i for i in items.value if _norm(i["name"]) == _norm(ticker)]
        if not exact:
            names = ", ".join(f"{i['name']}({i['short_code']})" for i in items.value[:5])
            raise NotFoundError(
                f"'{ticker}'와 이름이 정확히 같은 종목이 없습니다."
                + (f" 비슷한 종목: {names}" if names else "")
            )
        code = exact[0]["short_code"]

    raw = await app.fsc.stock_prices(code, start, end)
    fetched.append(raw)
    rows = [
        PriceRow(
            date=ymd_to_iso(r["basDt"]),
            open=to_int(r.get("mkp")) or 0,
            high=to_int(r.get("hipr")) or 0,
            low=to_int(r.get("lopr")) or 0,
            close=to_int(r.get("clpr")) or 0,
            volume=to_int(r.get("trqu")) or 0,
            trading_value=to_int(r.get("trPrc")),
            change=to_int(r.get("vs")),
            change_pct=to_float(r.get("fltRt")),
            market_cap=to_int(r.get("mrktTotAmt")),
        )
        for r in raw.value
    ]
    warnings = ["수정주가가 아닙니다. 기간 안에 액면분할·증자 등이 있으면 수익률이 왜곡됩니다."]
    if not rows:
        warnings.append("해당 기간에 시세 자료가 없습니다. 종목코드와 기간을 확인하세요.")
    last = raw.value[-1] if raw.value else {}
    data = Prices(
        short_code=code,
        name=last.get("itmsNm"),
        isin=last.get("isinCd"),
        market=last.get("mrktCtg"),
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        prices=rows,
    )
    summary = analytics.price_summary([r.model_dump() for r in rows])
    as_of = rows[-1].date if rows else end.isoformat()
    return _envelope(
        fsc_api.SOURCE_PRICES, as_of, data, *fetched, computed=summary, warnings=warnings
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
