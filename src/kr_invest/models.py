"""도구 응답의 정규화 스키마."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

DISCLAIMER = (
    "공식 API 데이터를 정리한 참고 자료이며 투자 권유가 아닙니다. "
    "투자 판단과 그 결과의 책임은 이용자 본인에게 있습니다."
)


class Envelope(BaseModel):
    """모든 도구가 돌려주는 공통 형식."""

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
    short_code: str
    name: str
    isin: str | None = None
    corp_code: str | None = Field(default=None, description="DART 고유번호(8자리)")
    market: str | None = Field(default=None, description="KOSPI, KOSDAQ, KONEX")


class TickerResult(BaseModel):
    query: str
    match: Ticker | None = Field(description="하나로 확정된 종목. 모호하면 null")
    candidates: list[Ticker] = Field(default_factory=list)


class Disclosure(BaseModel):
    rcept_no: str = Field(description="접수번호(14자리). get_disclosure_text에 넘긴다")
    title: str
    date: str
    filer: str
    corp_name: str
    remark: str = ""
    url: str = Field(description="DART 뷰어 링크(출처 표기용)")


class DisclosureList(BaseModel):
    corp_code: str
    corp_name: str
    start_date: str
    end_date: str
    disclosure_type: str | None
    total_count: int
    disclosures: list[Disclosure]


class DisclosureText(BaseModel):
    rcept_no: str
    url: str
    total_chars: int
    offset: int
    returned_chars: int
    truncated: bool
    next_offset: int | None
    text: str


class Account(BaseModel):
    """재무 계정 한 줄. 금액 단위는 원."""

    label: str = Field(description="DART 계정명")
    current: int | None = Field(description="당기 금액. 분기·반기 손익 항목은 3개월 금액")
    current_period: str | None = None
    prior: int | None = Field(
        description="비교 금액. 손익은 전년 동기, 재무상태표는 전기말(분기) 또는 전년말(연간)"
    )
    prior_period: str | None = None
    cumulative: int | None = Field(default=None, description="당기 누적 금액(분기·반기 손익만)")
    prior_cumulative: int | None = None


class Financials(BaseModel):
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
    short_code: str
    name: str | None
    isin: str | None
    market: str | None
    start_date: str
    end_date: str
    prices: list[PriceRow]
