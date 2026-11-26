"""도구 응답의 정규화 스키마."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

DISCLAIMER = (
    "공식 API 데이터를 정리한 참고 자료이며 투자 권유가 아닙니다. "
    "투자 판단과 그 결과의 책임은 이용자 본인에게 있습니다."
)


class Envelope(BaseModel):
    """모든 도구가 돌려주는 공통 형식.

    Attributes:
        source: 데이터 출처(공식 API 이름).
        as_of: 데이터 기준일 또는 기준 시각(KST).
        fetched_at: API에서 실제로 받아 온 시각(KST).
        cached: 캐시에서 읽었는지 여부.
        data: 도구별 결과.
        computed: 서버가 코드로 계산한 파생 수치(수익률, 증감률 등).
        warnings: 결과를 읽을 때 알아야 할 주의 사항.
        disclaimer: 투자 권유가 아니라는 고지.
    """

    source: str = Field(description="데이터 출처(공식 API 이름)")
    as_of: str = Field(description="데이터 기준일 또는 기준 시각(KST)")
    fetched_at: str = Field(description="API에서 실제로 받아 온 시각(KST)")
    cached: bool = Field(description="캐시에서 읽었는지 여부")
    data: Any
    computed: dict[str, Any] | None = Field(
        default=None, description="서버가 코드로 계산한 파생 수치(수익률, 증감률 등)"
    )
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER


class Ticker(BaseModel):
    """종목 한 건의 식별자 묶음. 소스에서 받지 못한 항목은 None이다.

    Attributes:
        short_code: 6자리 단축코드.
        name: 종목명.
        isin: ISIN 코드.
        corp_code: DART 고유번호(8자리).
        market: KOSPI, KOSDAQ, KONEX 중 하나.
    """

    short_code: str
    name: str
    isin: str | None = None
    corp_code: str | None = Field(default=None, description="DART 고유번호(8자리)")
    market: str | None = Field(default=None, description="KOSPI, KOSDAQ, KONEX")


class TickerResult(BaseModel):
    """resolve_ticker의 data.

    Attributes:
        query: 입력한 검색어.
        match: 하나로 확정된 종목. 모호하면 None.
        candidates: 검색에 걸린 종목들(최대 10건). 하나로 확정됐고 그것뿐이면 비어 있다.
    """

    query: str
    match: Ticker | None = Field(description="하나로 확정된 종목. 모호하면 null")
    candidates: list[Ticker] = Field(default_factory=list)


class Disclosure(BaseModel):
    """공시 한 건.

    Attributes:
        rcept_no: 접수번호(14자리). get_disclosure_text에 넘긴다.
        title: 보고서 이름.
        date: 접수일(YYYY-MM-DD).
        filer: 제출인.
        corp_name: 회사 이름.
        remark: DART의 비고 표시('유', '공' 등).
        url: DART 뷰어 링크.
    """

    rcept_no: str = Field(description="접수번호(14자리). get_disclosure_text에 넘긴다")
    title: str
    date: str
    filer: str
    corp_name: str
    remark: str = ""
    url: str = Field(description="DART 뷰어 링크(출처 표기용)")


class DisclosureList(BaseModel):
    """list_disclosures의 data.

    Attributes:
        corp_code: DART 고유번호.
        corp_name: 회사 이름.
        start_date: 조회 시작일(YYYY-MM-DD).
        end_date: 조회 종료일(YYYY-MM-DD).
        disclosure_type: 공시유형 이름. 걸러 내지 않았으면 None.
        total_count: 기간 안의 전체 건수.
        disclosures: 공시 목록(최신순, limit까지).
    """

    corp_code: str
    corp_name: str
    start_date: str
    end_date: str
    disclosure_type: str | None
    total_count: int
    disclosures: list[Disclosure]


class DisclosureText(BaseModel):
    """get_disclosure_text의 data.

    Attributes:
        rcept_no: 접수번호.
        url: DART 뷰어 링크.
        total_chars: 본문 전체 글자 수.
        offset: 이번에 돌려준 부분의 시작 위치.
        returned_chars: 이번에 돌려준 글자 수.
        truncated: 뒤에 남은 본문이 있는지.
        next_offset: 이어 읽을 위치. 끝까지 읽었으면 None.
        text: 본문 텍스트.
    """

    rcept_no: str
    url: str
    total_chars: int
    offset: int
    returned_chars: int
    truncated: bool
    next_offset: int | None
    text: str


class Account(BaseModel):
    """재무 계정 한 줄. 금액 단위는 원.

    Attributes:
        label: DART 계정명.
        current: 당기 금액. 분기·반기 손익 항목은 3개월 금액.
        current_period: current 금액의 기간. 분기·반기 손익은 해당 3개월 구간.
        prior: 비교 금액. 손익은 전년 동기, 재무상태표는 전기말(분기) 또는 전년말(연간).
        prior_period: prior 금액의 기간.
        cumulative: 당기 누적 금액(분기·반기 손익만).
        prior_cumulative: 전년 동기 누적 금액(분기·반기 손익만).
    """

    label: str = Field(description="DART 계정명")
    current: int | None = Field(description="당기 금액. 분기·반기 손익 항목은 3개월 금액")
    current_period: str | None = Field(
        default=None, description="current 금액의 기간. 분기·반기 손익은 해당 3개월 구간"
    )
    prior: int | None = Field(
        description="비교 금액. 손익은 전년 동기, 재무상태표는 전기말(분기) 또는 전년말(연간)"
    )
    prior_period: str | None = None
    cumulative: int | None = Field(default=None, description="당기 누적 금액(분기·반기 손익만)")
    prior_cumulative: int | None = None


class Financials(BaseModel):
    """get_financials의 data.

    Attributes:
        corp_code: DART 고유번호.
        corp_name: 회사 이름.
        year: 사업연도.
        quarter: 분기(1~3) 또는 4(사업보고서).
        report: 보고서 이름.
        period_type: annual 또는 quarter.
        statement: 연결재무제표 또는 재무제표(별도).
        currency: 통화.
        rcept_no: 근거가 된 보고서의 접수번호.
        accounts: 계정 키 → 계정. 응답에서 찾지 못한 계정은 None.
    """

    corp_code: str
    corp_name: str
    year: int
    quarter: int
    report: str
    period_type: str = Field(description="annual 또는 quarter")
    statement: str | None = Field(description="연결재무제표 또는 재무제표(별도)")
    currency: str | None = None
    rcept_no: str | None = None
    accounts: dict[str, Account | None]


class PriceRow(BaseModel):
    """하루치 시세. 수정주가가 아니다.

    Attributes:
        date: 기준일(YYYY-MM-DD).
        open: 시가(원).
        high: 고가(원).
        low: 저가(원).
        close: 종가(원).
        volume: 거래량(주).
        trading_value: 거래대금(원).
        change: 전일 대비(원).
        change_pct: 전일 대비 등락률(%).
        market_cap: 시가총액(원).
    """

    date: str
    open: int
    high: int
    low: int
    close: int
    volume: int
    trading_value: int | None = None
    change: int | None = None
    change_pct: float | None = None
    market_cap: int | None = None


class Prices(BaseModel):
    """get_stock_prices의 data.

    Attributes:
        short_code: 6자리 단축코드.
        name: 종목명. 시세가 없으면 None.
        isin: ISIN 코드. 시세가 없으면 None.
        market: 시장 구분. 시세가 없으면 None.
        start_date: 조회 시작일(YYYY-MM-DD).
        end_date: 조회 종료일(YYYY-MM-DD).
        prices: 일별 시세(날짜 오름차순).
    """

    short_code: str
    name: str | None
    isin: str | None
    market: str | None
    start_date: str
    end_date: str
    prices: list[PriceRow]
