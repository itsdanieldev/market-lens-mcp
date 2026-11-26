"""날짜·숫자 파싱 도우미. 모든 날짜는 한국 시간(KST) 기준."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from .errors import InvalidInputError

KST = timezone(timedelta(hours=9))


def is_stock_code(query: str) -> bool:
    """'005930', 'A005930'처럼 종목코드 모양인지."""
    return bool(re.fullmatch(r"[Aa]?\d[0-9A-Za-z]{5}", query.strip()))


def clean_stock_code(code: str) -> str:
    """'A005930'처럼 접두 문자가 붙은 단축코드를 6자리로 바꾼다."""
    text = (code or "").strip().upper()
    return text[1:] if len(text) == 7 and text[0].isalpha() else text


def norm_name(name: str) -> str:
    """이름 비교용: 공백을 없애고 대소문자를 무시한다."""
    return re.sub(r"\s+", "", name).casefold()


def now_kst() -> datetime:
    """한국 시간(KST) 기준 현재 시각."""
    return datetime.now(KST)


def iso_kst(epoch: float) -> str:
    """epoch 초를 KST ISO 8601 문자열(초 단위)로 바꾼다."""
    return datetime.fromtimestamp(epoch, KST).isoformat(timespec="seconds")


def parse_date(value: str | None, *, default: date) -> date:
    """'YYYY-MM-DD' 또는 'YYYYMMDD'를 날짜로 바꾼다."""
    if value is None or not value.strip():
        return default
    digits = re.sub(r"[-./\s]", "", value)
    try:
        return datetime.strptime(digits, "%Y%m%d").date()
    except ValueError:
        raise InvalidInputError(f"날짜 형식이 잘못됐습니다: {value!r} (예: 2025-01-31)") from None


def ymd(d: date) -> str:
    """날짜를 'YYYYMMDD'로 바꾼다(API 요청용)."""
    return d.strftime("%Y%m%d")


def ymd_to_iso(value: str) -> str:
    """'YYYYMMDD'를 'YYYY-MM-DD'로 바꾼다. 8자리가 아니면 그대로 돌려준다."""
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
    """'-.96', '1,234.5', '-', '' 같은 API 문자열을 실수로 바꾼다. 값이 없으면 None."""
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if text in ("", "-"):
        return None
    try:
        return float(text)
    except ValueError:
        return None
