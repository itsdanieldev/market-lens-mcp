"""get_financials: DART 주요계정에서 계정을 고르고 증감률·이익률·부채비율을 계산한다."""

from __future__ import annotations

import re
from typing import Any

from .. import analytics
from ..errors import NotFoundError
from ..models import Account, Financials
from ..sources import dart as dart_api
from ..util import norm_name
from ._common import envelope, find_corp

REPORT_NAMES = {1: "1분기보고서", 2: "반기보고서", 3: "3분기보고서", 4: "사업보고서"}
ANNUAL = 4
# 응답 키 → DART 계정명 판별. 계정을 더하려면 여기에 한 줄을 더한다.
ACCOUNT_MATCHERS = {
    "revenue": lambda n: n in ("매출액", "수익(매출액)", "영업수익"),
    "operating_income": lambda n: n.startswith("영업이익"),
    "net_income": lambda n: n.startswith(("당기순이익", "분기순이익", "반기순이익")),
    "total_assets": lambda n: n == "자산총계",
    "total_liabilities": lambda n: n == "부채총계",
    "total_equity": lambda n: n == "자본총계",
}


def three_months(period: str | None) -> str | None:
    """'2025.01.01 ~ 2025.09.30' 같은 누적 구간을 마지막 3개월 구간으로 바꾼다."""
    found = re.fullmatch(r"\s*\d{4}\.\d{2}\.\d{2}\s*~\s*((\d{4})\.(\d{2})\.\d{2})\s*", period or "")
    if not found:
        return period
    months = int(found.group(2)) * 12 + int(found.group(3)) - 3  # 0부터 센 시작 월
    return f"{months // 12}.{months % 12 + 1:02d}.01 ~ {found.group(1)}"


def _pick_accounts(
    rows: list[dict[str, Any]], quarter: int, warnings: list[str]
) -> dict[str, Account | None]:
    accounts: dict[str, Account | None] = {}
    for key, matches in ACCOUNT_MATCHERS.items():
        row = next((r for r in rows if matches(norm_name(r["name"]))), None)
        if row is None:
            accounts[key] = None
            warnings.append(f"{key} 계정을 응답에서 찾지 못했습니다.")
            continue
        # 분기·반기 손익의 기간 표기는 누적 구간인데 금액은 3개월분이라 기간을 금액에 맞춘다.
        narrow = quarter != ANNUAL and row["is_income"]
        accounts[key] = Account(
            label=row["name"],
            current=row["current"],
            current_period=three_months(row["current_period"]) if narrow else row["current_period"],
            prior=row["prior"],
            prior_period=three_months(row["prior_period"]) if narrow else row["prior_period"],
            cumulative=row["cumulative"],
            prior_cumulative=row["prior_cumulative"],
        )
    return accounts


def _compute(accounts: dict[str, Account | None]) -> dict[str, Any]:
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
    return computed


async def get_financials(
    dart: dart_api.DartClient, ticker: str, year: int, quarter: int
) -> dict[str, Any]:
    corp = await find_corp(dart, ticker)
    fetched = await dart.financials(corp["corp_code"], year, quarter)
    rows: list[dict[str, Any]] = fetched.value
    if not rows:
        raise NotFoundError(
            f"{corp['corp_name']} {year}년 {REPORT_NAMES[quarter]}의 재무 자료가 DART에 없습니다. "
            "아직 제출 전이거나 대상이 아닐 수 있습니다."
        )
    warnings: list[str] = []
    consolidated = any(r["consolidated"] for r in rows)
    if not consolidated:
        warnings.append("연결재무제표가 없어 별도재무제표 기준입니다.")
    rows = [r for r in rows if r["consolidated"] == consolidated]

    accounts = _pick_accounts(rows, quarter, warnings)
    computed = _compute(accounts)
    if any(a and a.prior is not None and a.prior <= 0 for a in accounts.values()):
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
        period_type="annual" if quarter == ANNUAL else "quarter",
        statement=first["statement"],
        currency=first["currency"],
        rcept_no=first["rcept_no"],
        accounts=accounts,
    )
    return envelope(dart_api.SOURCE, as_of, data, fetched, computed=computed, warnings=warnings)
