"""날짜·숫자 파싱 도우미. 모든 날짜는 한국 시간(KST) 기준."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from .errors import InvalidInputError

KST = timezone(timedelta(hours=9))


def is_stock_code(query: str) -> bool:
    """종목코드 모양인지 확인한다.

    Args:
        query: 확인할 문자열.

    Returns:
        '005930', 'A005930'처럼 종목코드 모양이면 True.
    """
    return bool(re.fullmatch(r"[Aa]?\d[0-9A-Za-z]{5}", query.strip()))


def clean_stock_code(code: str) -> str:
    """접두 문자가 붙은 단축코드를 6자리로 바꾼다.

    Args:
        code: 'A005930' 또는 '005930' 같은 코드.

    Returns:
        대문자로 바꾸고 접두 문자를 뗀 6자리 코드.
    """
    text = (code or "").strip().upper()
    return text[1:] if len(text) == 7 and text[0].isalpha() else text


def norm_name(name: str) -> str:
    """이름을 비교용으로 정규화한다.

    Args:
        name: 종목명이나 회사명.

    Returns:
        공백을 없애고 대소문자를 통일한 문자열.
    """
    return re.sub(r"\s+", "", name).casefold()


def now_kst() -> datetime:
    """한국 시간(KST) 기준 현재 시각을 돌려준다.

    Returns:
        시간대가 KST인 현재 시각.
    """
    return datetime.now(KST)


def iso_kst(epoch: float) -> str:
    """epoch 초를 KST 기준 ISO 8601 문자열로 바꾼다.

    Args:
        epoch: epoch 초.

    Returns:
        '2026-11-26T13:31:34+09:00' 같은 초 단위 문자열.
    """
    return datetime.fromtimestamp(epoch, KST).isoformat(timespec="seconds")


def parse_date(value: str | None, *, default: date) -> date:
    """날짜 문자열을 날짜로 바꾼다.

    Args:
        value: 'YYYY-MM-DD' 또는 'YYYYMMDD'. 구분자는 '-', '.', '/'를 받는다.
        default: value가 None이거나 비어 있을 때 돌려줄 날짜.

    Returns:
        해석한 날짜.

    Raises:
        InvalidInputError: 날짜로 읽을 수 없을 때.
    """
    if value is None or not value.strip():
        return default
    digits = re.sub(r"[-./\s]", "", value)
    try:
        return datetime.strptime(digits, "%Y%m%d").date()
    except ValueError:
        raise InvalidInputError(f"날짜 형식이 잘못됐습니다: {value!r} (예: 2025-01-31)") from None


def ymd(d: date) -> str:
    """날짜를 API 요청용 문자열로 바꾼다.

    Args:
        d: 날짜.

    Returns:
        'YYYYMMDD' 문자열.
    """
    return d.strftime("%Y%m%d")


def ymd_to_iso(value: str) -> str:
    """API의 날짜 문자열을 ISO 형식으로 바꾼다.

    Args:
        value: 'YYYYMMDD' 문자열.

    Returns:
        'YYYY-MM-DD' 문자열. 8자리가 아니면 받은 값 그대로.
    """
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}" if len(value) == 8 else value


def to_int(value: object) -> int | None:
    """API의 문자열 금액을 정수로 바꾼다.

    Args:
        value: '1,234', '-1,000' 같은 값.

    Returns:
        정수. None, '', '-'이거나 숫자로 읽을 수 없으면 None.
    """
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
    """API의 문자열 숫자를 실수로 바꾼다.

    Args:
        value: '-.96', '1,234.5' 같은 값.

    Returns:
        실수. None, '', '-'이거나 숫자로 읽을 수 없으면 None.
    """
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if text in ("", "-"):
        return None
    try:
        return float(text)
    except ValueError:
        return None
