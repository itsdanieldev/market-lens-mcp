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
    """누적 구간 표기를 마지막 3개월 구간으로 바꾼다.

    Args:
        period: '2025.01.01 ~ 2025.09.30' 같은 기간 표기.

    Returns:
        '2025.07.01 ~ 2025.09.30'처럼 끝에서 3개월인 구간. 구간 형식이 아니면
        ('2025.09.30 현재', None 등) 받은 값 그대로.
    """
    found = re.fullmatch(r"\s*\d{4}\.\d{2}\.\d{2}\s*~\s*((\d{4})\.(\d{2})\.\d{2})\s*", period or "")
    if not found:
        return period
    months = int(found.group(2)) * 12 + int(found.group(3)) - 3  # 0부터 센 시작 월
    return f"{months // 12}.{months % 12 + 1:02d}.01 ~ {found.group(1)}"


def _pick_accounts(
    rows: list[dict[str, Any]], quarter: int, warnings: list[str]
) -> dict[str, Account | None]:
    """계정 목록에서 ACCOUNT_MATCHERS에 맞는 계정을 고른다.

    Args:
        rows: dart.financials가 돌려준 계정 목록(한 가지 재무제표 기준으로 걸러 낸 것).
        quarter: 분기(1~3) 또는 4(사업보고서). 분기 손익의 기간 표기를 고치는 데 쓴다.
        warnings: 찾지 못한 계정을 적어 넣을 목록. 이 함수가 내용을 더한다.

    Returns:
        계정 키 → Account. 찾지 못한 계정은 None.
    """
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
    """이익률, 부채비율, 계정별 증감률을 계산한다.

    Args:
        accounts: 계정 키 → Account 또는 None.

    Returns:
        파생 수치 dict. 계산할 수 없는 값은 None이고, 누적 증감률은 누적 금액이
        있는 계정에만 들어간다.
    """

    def cur(key: str) -> int | None:
        """계정의 당기 금액을 꺼낸다.

        Args:
            key: 계정 키.

        Returns:
            당기 금액. 계정이 없으면 None.
        """
        return accounts[key].current if accounts[key] else None

    def prior(key: str) -> int | None:
        """계정의 비교 금액을 꺼낸다.

        Args:
            key: 계정 키.

        Returns:
            비교 금액. 계정이 없으면 None.
        """
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
    """한 회사의 주요 계정과 파생 수치를 돌려준다.

    연결재무제표가 있으면 연결, 없으면 별도 기준이다.

    Args:
        dart: DART 클라이언트.
        ticker: 종목명 또는 6자리 종목코드.
        year: 사업연도.
        quarter: 1~3은 해당 분기 보고서, 4는 사업보고서.

    Returns:
        Financials를 담은 공통 형식. as_of는 당기 기간의 마지막 날이고,
        computed에 증감률, 이익률, 부채비율이 들어 있다.

    Raises:
        NotFoundError: 일치하는 상장사가 없거나 해당 보고서의 재무 자료가 없을 때.
        SourceError: DART가 오류를 돌려줬을 때.
    """
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

    # 재무제표 이름, 통화, 접수번호는 같은 보고서의 모든 행에서 같아 첫 행에서 읽는다.
    first = rows[0]
    periods = [a.current_period for a in accounts.values() if a and a.current_period]
    # 기준일은 당기 기간 표기('~ 2025.09.30', '2025.09.30 현재')에 나온 날짜 가운데 가장 늦은 날이다.
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
