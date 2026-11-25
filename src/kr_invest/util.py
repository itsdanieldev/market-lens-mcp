"""날짜·숫자 파싱 도우미. 모든 날짜는 한국 시간(KST) 기준."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    return datetime.now(KST)


def iso_kst(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, KST).isoformat(timespec="seconds")


def parse_date(value: str | None, *, default: date) -> date:
    """'YYYY-MM-DD' 또는 'YYYYMMDD'를 날짜로 바꾼다."""
    if value is None or not value.strip():
        return default
    digits = re.sub(r"[-./\s]", "", value)
    try:
        return datetime.strptime(digits, "%Y%m%d").date()
    except ValueError:
        raise ValueError(f"날짜 형식이 잘못됐습니다: {value!r} (예: 2025-01-31)") from None


def ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def ymd_to_iso(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}" if len(value) == 8 else value


def to_int(value: object) -> int | None:
    """'1,234', '-', '' 같은 API 문자열 금액을 정수로 바꾼다."""
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if text in ("", "-"):
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def to_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if text in ("", "-"):
        return None
    try:
        return float(text)
    except ValueError:
        return None
