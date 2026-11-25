"""도구 5개를 픽스처 응답으로 검증한다."""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from mcp import Client

from kr_invest import server
from kr_invest.errors import MissingKeyError, NotFoundError, SourceError
from kr_invest.sources.dart import document_to_text

from .conftest import FIXTURES

ENVELOPE_KEYS = {"source", "as_of", "fetched_at", "cached", "data", "disclaimer"}


def assert_envelope(result: dict) -> None:
    assert result.keys() >= ENVELOPE_KEYS
    assert result["source"] and result["as_of"]


async def test_resolve_ticker_by_name(app):
    result = await server.resolve_ticker("삼성전자")
    assert_envelope(result)
    assert result["data"]["match"] == {
        "short_code": "005930",
        "name": "삼성전자",
        "isin": "KR7005930003",
        "corp_code": "00126380",
        "market": "KOSPI",
    }
    assert [c["short_code"] for c in result["data"]["candidates"]] == ["005930", "005935"]
    assert "KRX상장종목정보" in result["source"] and "DART" in result["source"]
    assert result["as_of"] == "2024-11-14"


async def test_resolve_ticker_by_code_and_no_dart_mapping(app):
    result = await server.resolve_ticker("005935")
    assert result["data"]["match"]["name"] == "삼성전자우"
    assert result["data"]["match"]["corp_code"] is None
    assert any("고유번호" in w for w in result["warnings"])


async def test_resolve_ticker_with_only_dart_key(make_app):
    make_app(fsc_key=None)
    result = await server.resolve_ticker("삼성전자")
    assert result["data"]["match"]["corp_code"] == "00126380"
    assert result["data"]["match"]["isin"] is None
    assert any("DATA_GO_KR_KEY" in w for w in result["warnings"])


async def test_list_disclosures(app, api):
    result = await server.list_disclosures(
        "삼성전자", start_date="2024-10-15", end_date="2024-11-14", disclosure_type="정기공시"
    )
    assert_envelope(result)
    data = result["data"]
    assert data["corp_code"] == "00126380" and data["disclosure_type"] == "정기공시"
    first = data["disclosures"][0]
    assert first["rcept_no"] == "20241114000001" and first["date"] == "2024-11-14"
    assert first["url"].endswith("rcpNo=20241114000001")
    assert result["computed"] == {"returned_count": 3, "has_more": False}
    params = next(r for r in api.calls if r.url.path.endswith("list.json")).url.params
    assert (params["bgn_de"], params["end_de"], params["pblntf_ty"]) == (
        "20241015",
        "20241114",
        "A",
    )


async def test_list_disclosures_no_data_and_bad_type(app, api):
    api.overrides["list.json"] = httpx.Response(
        200, json={"status": "013", "message": "조회된 데이타가 없습니다."}
    )
    result = await server.list_disclosures("005930")
    assert result["data"]["disclosures"] == [] and result["data"]["total_count"] == 0
    with pytest.raises(ValueError):
        await server.list_disclosures("005930", disclosure_type="없는유형")


async def test_get_disclosure_text_truncates_and_pages(app):
    full = await server.get_disclosure_text("20241031000003", max_chars=50_000)
    text = full["data"]["text"]
    assert "현금ㆍ현물배당 결정" in text and "1주당 배당금(원) | 100" in text
    assert "해당 없음 & 끝." in text
    assert "color" not in text and "<" not in text
    assert full["data"]["truncated"] is False and full["as_of"] == "2024-10-31"

    part = await server.get_disclosure_text("20241031000003", max_chars=500, offset=10)
    assert part["data"]["text"] == text[10:510]
    short = document_to_text("<P>" + "가" * 2000 + "</P>")
    assert len(short) == 2000


async def test_get_disclosure_text_rejects_bad_number(app):
    with pytest.raises(ValueError):
        await server.get_disclosure_text("1234")


async def test_get_financials_quarter(app):
    result = await server.get_financials("삼성전자", 2024, 3)
    assert_envelope(result)
    data, computed = result["data"], result["computed"]
    assert data["statement"] == "연결재무제표" and data["period_type"] == "quarter"
    assert data["accounts"]["revenue"]["current"] == 80_000_000_000
    assert data["accounts"]["revenue"]["cumulative"] == 220_000_000_000
    assert data["accounts"]["total_liabilities"]["current"] == 100_000_000_000
    assert computed["revenue_change_pct"] == 25.0
    assert computed["revenue_cumulative_change_pct"] == 10.0
    assert computed["operating_income_change_pct"] == 300.0
    assert computed["operating_margin_pct"] == 12.5
    assert computed["debt_to_equity_pct"] == 25.0
    assert computed["total_assets_change_pct"] == 25.0
    # 전년 동기가 적자면 증감률을 내지 않는다
    assert computed["net_income_change_pct"] is None
    assert any("0 이하" in w for w in result["warnings"])
    assert result["as_of"] == "2024-09-30"


async def test_get_financials_falls_back_to_separate_and_missing(app, api):
    payload = json.loads((FIXTURES / "dart_financials.json").read_text(encoding="utf-8"))
    payload["list"] = [r for r in payload["list"] if r["fs_div"] == "OFS"]
    api.overrides["fnlttSinglAcnt"] = httpx.Response(200, json=payload)
    result = await server.get_financials("005930", 2024, 3)
    assert result["data"]["statement"] == "재무제표"
    assert any("별도" in w for w in result["warnings"])

    api.overrides["fnlttSinglAcnt"] = httpx.Response(200, json={"status": "013", "message": "-"})
    with pytest.raises(NotFoundError):
        await server.get_financials("005930", 2025, 1)


async def test_get_stock_prices(app, api):
    result = await server.get_stock_prices("삼성전자", "2024-11-08", "2024-11-14")
    assert_envelope(result)
    prices = result["data"]["prices"]
    assert [p["date"] for p in prices] == [
        "2024-11-08", "2024-11-11", "2024-11-12", "2024-11-13", "2024-11-14",
    ]  # fmt: skip
    assert prices[-1] == {
        "date": "2024-11-14", "open": 53500, "high": 56000, "low": 53000, "close": 55000,
        "volume": 1800000, "trading_value": 99000000000, "change": 1500, "change_pct": 2.8,
        "market_cap": 328338040250000,
    }  # fmt: skip
    computed = result["computed"]
    assert computed["period_return_pct"] == 10.0
    assert computed["trading_days"] == 5 and computed["average_volume"] == 1_500_000
    assert computed["period_high"] == 56000 and computed["period_low_date"] == "2024-11-08"
    assert result["as_of"] == "2024-11-14" and result["source"].endswith("주식시세정보")
    params = next(r for r in api.calls if r.url.path.endswith("getStockPriceInfo")).url.params
    # endBasDt는 미만 조건이라 하루 뒤를 보낸다
    assert (params["beginBasDt"], params["endBasDt"]) == ("20241108", "20241115")


async def test_prices_are_cached_for_the_day(app, api):
    first = await server.get_stock_prices("005930", "2024-11-08", "2024-11-14")
    second = await server.get_stock_prices("005930", "2024-11-08", "2024-11-14")
    assert api.count("getStockPriceInfo") == 1
    assert (first["cached"], second["cached"]) == (False, True)
    assert second["fetched_at"] == first["fetched_at"]


async def test_missing_keys(make_app):
    make_app(dart_key=None, fsc_key=None)
    with pytest.raises(MissingKeyError, match="DART_API_KEY"):
        await server.get_financials("005930", 2024, 3)
    with pytest.raises(MissingKeyError, match="DATA_GO_KR_KEY"):
        await server.get_stock_prices("005930")


async def test_unknown_company_suggests_candidates(app):
    with pytest.raises(NotFoundError, match="삼성SDI"):
        await server.list_disclosures("삼성S")


async def test_source_errors_do_not_leak_keys(app, api):
    api.overrides["list.json"] = httpx.Response(
        200, json={"status": "010", "message": "등록되지 않은 인증키입니다."}
    )
    with pytest.raises(SourceError, match="010") as dart_error:
        await server.list_disclosures("005930")
    api.overrides["getStockPriceInfo"] = httpx.Response(
        200,
        text="<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
        "<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>"
        "</cmmMsgHeader></OpenAPI_ServiceResponse>",
    )
    with pytest.raises(SourceError, match="SERVICE_KEY_IS_NOT_REGISTERED_ERROR") as fsc_error:
        await server.get_stock_prices("005930")
    api.overrides["corpCode"] = httpx.Response(503)
    server.get_app().cache.set("dart:corp_index", None, -1)
    with pytest.raises(SourceError, match="HTTP 503") as http_error:
        await server.get_financials("005930", 2024, 3)
    assert api.count("corpCode") == 4  # 처음 1번 + 재시도 3번
    for error in (dart_error, fsc_error, http_error):
        assert "test-dart-key" not in str(error.value)
        assert "test-fsc-key" not in str(error.value)


async def test_no_solicitation_wording_in_structured_output(app):
    """본문 텍스트를 뺀 도구 응답에 투자 권유 표현이 섞이지 않는다."""
    outputs = [
        await server.resolve_ticker("삼성전자"),
        await server.list_disclosures("삼성전자"),
        await server.get_financials("삼성전자", 2024, 3),
        await server.get_stock_prices("삼성전자", "2024-11-08", "2024-11-14"),
    ]
    blob = json.dumps(outputs, ensure_ascii=False)
    for word in ("매수", "매도", "목표가", "추천"):
        assert word not in blob


async def test_tools_are_registered_with_mcp():
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    assert set(tools) == {
        "resolve_ticker",
        "list_disclosures",
        "get_disclosure_text",
        "get_financials",
        "get_stock_prices",
    }
    assert tools["get_financials"].input_schema["required"] == ["ticker", "year"]


async def test_request_urls_with_keys_are_not_logged(app, caplog):
    with caplog.at_level(logging.INFO):
        await server.list_disclosures("005930")
    assert "test-dart-key" not in caplog.text


async def test_error_messages_reach_the_mcp_client(make_app):
    """안내가 필요한 오류는 가려지지 않고 모델에게 전달된다."""
    make_app(dart_key=None)
    async with Client(server.mcp) as client:
        missing = await client.call_tool("get_financials", {"ticker": "005930", "year": 2024})
        bad_date = await client.call_tool(
            "get_stock_prices", {"ticker": "005930", "start_date": "어제"}
        )
        ok = await client.call_tool("resolve_ticker", {"query": "삼성전자"})
    assert missing.is_error and "DART_API_KEY" in missing.content[0].text
    assert bad_date.is_error and "날짜 형식" in bad_date.content[0].text
    assert not ok.is_error
    assert ok.structured_content["data"]["match"]["short_code"] == "005930"
