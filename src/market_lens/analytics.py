"""수익률·증감률·재무비율 계산.

LLM이 숫자를 암산하지 않도록 파생 수치는 모두 여기서 계산해 도구 응답에 싣는다.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def pct_change(current: float | None, prior: float | None) -> float | None:
    """증감률(%). 이전 값이 없거나 0 이하(적자 등)면 의미가 없어 None."""
    if current is None or prior is None or prior <= 0:
        return None
    return round((current - prior) / prior * 100, 2)


def ratio_pct(numerator: float | None, denominator: float | None) -> float | None:
    """비율(%). 분자나 분모가 없거나 분모가 0 이하면 None."""
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round(numerator / denominator * 100, 2)


def price_summary(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """일별 시세 행(date, close, high, low, volume)에서 기간 요약을 계산한다."""
    if not rows:
        return None
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    first, last = df.iloc[0], df.iloc[-1]
    high, low = df.loc[df["high"].idxmax()], df.loc[df["low"].idxmin()]
    daily = df["close"].pct_change().dropna()
    return {
        "start_date": first["date"],
        "end_date": last["date"],
        "trading_days": int(len(df)),
        "start_close": int(first["close"]),
        "end_close": int(last["close"]),
        "period_return_pct": pct_change(float(last["close"]), float(first["close"])),
        "period_high": int(high["high"]),
        "period_high_date": high["date"],
        "period_low": int(low["low"]),
        "period_low_date": low["date"],
        "average_volume": int(round(df["volume"].mean())),
        "daily_return_stdev_pct": round(float(daily.std()) * 100, 2) if len(daily) > 1 else None,
    }
