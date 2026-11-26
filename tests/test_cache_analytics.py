"""캐시, 계산 함수, 파싱 도우미를 API 없이 검증한다."""

from datetime import datetime

import pytest

from market_lens import analytics
from market_lens.cache import Cache, seconds_until_kst_midnight
from market_lens.util import KST, parse_date, to_int


def test_cache_roundtrip_and_expiry(tmp_path):
    """저장한 값을 그대로 읽고, 유효 기간이 지나면 읽히지 않는다."""
    now = [1000.0]
    cache = Cache(tmp_path / "sub" / "c.sqlite3", clock=lambda: now[0])
    cache.set("k", {"가": [1, 2]}, ttl_seconds=60)
    hit = cache.get("k")
    assert hit.value == {"가": [1, 2]} and hit.stored_at == 1000.0
    now[0] += 61
    assert cache.get("k") is None


def test_cache_persists_across_connections(tmp_path):
    """DB 파일을 다시 열어도 값이 남아 있다."""
    path = tmp_path / "c.sqlite3"
    Cache(path).set("k", 1, 60)
    assert Cache(path).get("k").value == 1


def test_seconds_until_kst_midnight():
    """KST 23시에는 자정까지 3600초가 남는다."""
    at = datetime(2024, 11, 14, 23, 0, 0, tzinfo=KST).timestamp()
    assert seconds_until_kst_midnight(at) == 3600


def test_pct_change():
    """증감률을 계산하고, 이전 값이 없거나 0 이하면 None을 돌려준다."""
    assert analytics.pct_change(110, 100) == 10.0
    assert analytics.pct_change(90, 100) == -10.0
    assert analytics.pct_change(100, 0) is None
    assert analytics.pct_change(100, -50) is None
    assert analytics.pct_change(None, 100) is None


def test_price_summary():
    """행 순서와 상관없이 기간 수익률, 고가·저가, 평균 거래량을 계산한다."""
    rows = [
        {"date": "2024-01-03", "close": 120, "high": 125, "low": 100, "volume": 300},
        {"date": "2024-01-02", "close": 100, "high": 110, "low": 90, "volume": 100},
    ]
    summary = analytics.price_summary(rows)
    assert summary["period_return_pct"] == 20.0
    assert (summary["start_date"], summary["end_date"]) == ("2024-01-02", "2024-01-03")
    assert (summary["period_high"], summary["period_low_date"]) == (125, "2024-01-02")
    assert summary["average_volume"] == 200
    assert analytics.price_summary([]) is None


def test_parsers():
    """쉼표·빈 값이 섞인 금액과 여러 형식의 날짜를 읽고, 잘못된 날짜는 거부한다."""
    assert to_int("1,234,567") == 1234567
    assert to_int("-") is None and to_int("") is None
    assert to_int("-1,000") == -1000
    assert parse_date("2024.01.31", default=None).isoformat() == "2024-01-31"
    with pytest.raises(ValueError):
        parse_date("어제", default=None)
