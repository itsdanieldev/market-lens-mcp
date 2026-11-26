"""도구 5개를 픽스처 응답으로 검증한다.

DART 픽스처는 실제 응답 녹화본이다. 공공데이터포털(fsc_*) 픽스처는 실제 응답과 같은 구조에
지어낸 값을 넣은 샘플이다(이유는 tests/fixtures/README.md).
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from mcp import Client

from market_lens import server
from market_lens.app import get_app
from market_lens.errors import MissingKeyError, NotFoundError, SourceError
from market_lens.services.financials import three_months
from market_lens.sources.dart import document_to_text

from .conftest import FIXTURES

ENVELOPE_KEYS = {"source", "as_of", "citation", "fetched_at", "cached", "data", "disclaimer"}


def assert_envelope(result: dict) -> None:
    """도구 응답이 공통 형식인지 확인한다.

    Args:
        result: 도구가 돌려준 응답.
    """
    assert result.keys() >= ENVELOPE_KEYS
    assert result["source"] and result["as_of"]
    assert result["citation"] == f"출처: {result['source']} · 기준일: {result['as_of']}"


async def test_resolve_ticker_by_name(app):
    """종목명으로 찾으면 두 소스의 식별자가 모두 채워진다."""
    result = await server.resolve_ticker("삼성전자")
    assert_envelope(result)
    assert result["data"]["match"] == {
        "short_code": "005930",
        "name": "삼성전자",
        "isin": "KR7005930003",
        "corp_code": "00126380",
        "market": "KOSPI",
    }
    # 실제 응답처럼 같은 종목이 기준일마다 한 줄씩(최신순) 오고, 그중 최신 기준일 한 건만 남긴다
    assert result["data"]["candidates"] == []
    assert "KRX상장종목정보" in result["source"] and "DART" in result["source"]
    assert result["as_of"] == "2024-11-14"
    assert result["warnings"] == []


async def test_resolve_ticker_by_code(app, api):
    """종목코드로 찾으면 포털에 이름이 아니라 코드로 검색한다."""
    result = await server.resolve_ticker("005930")
    assert result["data"]["match"]["name"] == "삼성전자"
    assert result["data"]["match"]["isin"] == "KR7005930003"
    params = next(r for r in api.calls if r.url.path.endswith("/getItemInfo_V2")).url.params
    assert params["likeSrtnCd"] == "005930" and "likeItmsNm" not in params


def items_with_extra_listing() -> dict:
    """샘플에 DART 고유번호가 없는 종목 한 줄을 덧붙인다.

    실제 KRX상장종목정보는 우선주를 주지 않아 샘플에도 삼성전자 보통주만 있다.
    여러 종목이 걸리는 경우와 고유번호가 없는 경우를 보려고 지어낸 한 줄을 더한다.
    """
    payload = json.loads((FIXTURES / "fsc_items.json").read_text(encoding="utf-8"))
    rows = payload["response"]["body"]["items"]["item"]
    rows.append({**rows[0], "srtnCd": "A005935", "isinCd": "KR7005931001", "itmsNm": "삼성전자우"})
    payload["response"]["body"]["totalCount"] = len(rows)
    return payload


async def test_resolve_ticker_candidates_and_no_dart_mapping(app, api):
    """여러 종목이 걸리면 후보로 돌려주고, DART 고유번호가 없는 종목은 경고한다."""
    api.overrides["getItemInfo"] = httpx.Response(200, json=items_with_extra_listing())
    by_code = await server.resolve_ticker("005935")
    assert by_code["data"]["match"]["name"] == "삼성전자우"
    assert by_code["data"]["match"]["corp_code"] is None
    assert any("고유번호" in w for w in by_code["warnings"])
    by_name = await server.resolve_ticker("삼성전자")
    assert by_name["data"]["match"]["short_code"] == "005930"
    assert [c["short_code"] for c in by_name["data"]["candidates"]] == ["005930", "005935"]


async def test_resolve_ticker_without_listing(app, api):
    """포털에 종목이 없으면 확정하지 않고 경고한다(우선주가 이렇게 된다)."""
    payload = json.loads((FIXTURES / "fsc_items.json").read_text(encoding="utf-8"))
    payload["response"]["body"].update(totalCount=0, items="")
    api.overrides["getItemInfo"] = httpx.Response(200, json=payload)
    result = await server.resolve_ticker("005935")
    assert result["data"]["match"] is None and result["data"]["candidates"] == []
    assert any("일치하는 상장 종목이 없습니다" in w for w in result["warnings"])


async def test_resolve_ticker_with_only_dart_key(make_app):
    """포털 키가 없어도 DART만으로 종목코드와 corp_code를 돌려준다."""
    make_app(fsc_key=None)
    result = await server.resolve_ticker("삼성전자")
    assert result["data"]["match"]["corp_code"] == "00126380"
    assert result["data"]["match"]["isin"] is None
    assert any("DATA_GO_KR_KEY" in w for w in result["warnings"])


async def test_resolve_ticker_falls_back_to_dart_when_portal_fails(make_app, api):
    """포털 조회가 실패하면 DART로 답하고, DART도 없으면 오류를 그대로 알린다."""
    api.overrides["getItemInfo"] = httpx.Response(
        403,
        json={
            "OpenAPI_ServiceResponse": {
                "cmmMsgHeader": {"errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"}
            }
        },
    )
    make_app()
    result = await server.resolve_ticker("삼성전자")
    assert_envelope(result)
    assert result["data"]["match"] == {
        "short_code": "005930",
        "name": "삼성전자",
        "isin": None,
        "corp_code": "00126380",
        "market": None,
    }
    assert result["source"] == "DART OpenAPI (금융감독원 전자공시시스템)"
    assert any(
        "공공데이터포털" in w and "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in w
        for w in result["warnings"]
    )
    assert "test-fsc-key" not in json.dumps(result, ensure_ascii=False)

    # DART 키마저 없으면 대신 답할 곳이 없으므로 오류를 그대로 알린다
    make_app(dart_key=None)
    with pytest.raises(SourceError, match="SERVICE_KEY_IS_NOT_REGISTERED_ERROR"):
        await server.resolve_ticker("삼성전자")


async def test_list_disclosures(app, api):
    """공시 목록을 정규화해 돌려주고 기간과 공시유형을 DART 형식으로 보낸다."""
    result = await server.list_disclosures(
        "삼성전자",
        start_date="2026-10-26",
        end_date="2026-11-25",
        disclosure_type="정기공시",
        limit=20,
    )
    assert_envelope(result)
    data = result["data"]
    assert data["corp_code"] == "00126380" and data["disclosure_type"] == "정기공시"
    assert data["total_count"] == 41
    first = data["disclosures"][0]
    assert first["rcept_no"] == "20261118000151" and first["date"] == "2026-11-18"
    assert first["title"] == "임원ㆍ주요주주특정증권등소유상황보고서"
    assert first["url"].endswith("rcpNo=20261118000151")
    quarterly = data["disclosures"][1]
    assert quarterly["title"] == "분기보고서 (2026.09)" and quarterly["filer"] == "삼성전자"
    # 실제 응답은 제목 뒤에 공백이 붙어 오고, 비고(rm)에 '유', '공' 같은 표시가 온다
    notice = data["disclosures"][2]
    assert notice["title"] == "최대주주등소유주식변동신고서" and notice["remark"] == "유"
    assert result["computed"] == {"returned_count": 20, "has_more": True}
    assert api.count("list.json") == 1
    params = next(r for r in api.calls if r.url.path.endswith("list.json")).url.params
    assert (params["bgn_de"], params["end_de"], params["pblntf_ty"]) == (
        "20261026",
        "20261125",
        "A",
    )


async def test_list_disclosures_no_data_and_bad_type(app, api):
    """자료가 없으면 빈 목록을 돌려주고, 모르는 공시유형은 거부한다."""
    api.overrides["list.json"] = httpx.Response(
        200, json={"status": "013", "message": "조회된 데이타가 없습니다."}
    )
    result = await server.list_disclosures("005930")
    assert result["data"]["disclosures"] == [] and result["data"]["total_count"] == 0
    with pytest.raises(ValueError):
        await server.list_disclosures("005930", disclosure_type="없는유형")


async def test_get_disclosure_text_truncates_and_pages(app):
    """원문을 줄 단위 텍스트로 바꾸고, 길면 잘라 next_offset으로 이어 읽게 한다."""
    full = await server.get_disclosure_text("20261118000151", max_chars=50_000)
    text = full["data"]["text"]
    lines = text.split("\n")
    assert lines[0] == "임원ㆍ주요주주 특정증권등 소유상황보고서" and lines[1] == "삼성전자"
    # 표의 한 행이 한 줄로 나온다
    assert "법인구분 | 유가증권상장법인 | 회사코드 | 005930 |" in lines
    assert "직전보고서 | 2026년 01월 30일 | 1,206 | 0.00 | 1,206 | 0.00 |" in lines
    assert "1. 발행회사에 관한 사항" in lines
    # 서식 버전 같은 머리 정보와 태그는 남지 않는다
    assert "6.1" not in lines and "<" not in text and "AUNITVALUE" not in text
    assert full["data"]["total_chars"] == len(text) == 1770
    assert full["data"]["truncated"] is False and full["as_of"] == "2026-11-18"

    part = await server.get_disclosure_text("20261118000151", max_chars=500, offset=10)
    assert part["data"]["text"] == text[10:510]
    assert part["data"]["truncated"] is True and part["data"]["next_offset"] == 510
    short = document_to_text("<P>" + "가" * 2000 + "</P>")
    assert len(short) == 2000


def test_document_to_text_handles_html_style_markup():
    """HTML식 마크업에서도 스타일과 태그를 걷어 내고 표의 행을 한 줄로 만든다."""
    markup = (
        "<BODY><STYLE>.x { color: red; }</STYLE><TITLE>배당 결정</TITLE>"
        "<TABLE><TR><TD>1주당 배당금(원)</TD><TD>100</TD></TR></TABLE>"
        "<P>중요사항:&nbsp;해당 없음 &amp; 끝.<BR/>다음 줄</P></BODY>"
    )
    assert document_to_text(markup).split("\n") == [
        "배당 결정",
        "1주당 배당금(원) | 100 |",
        "중요사항: 해당 없음 & 끝.",
        "다음 줄",
    ]


def test_quarter_income_period_is_narrowed_to_three_months():
    """누적 구간 표기를 마지막 3개월로 바꾸고, 구간이 아니면 그대로 둔다."""
    assert three_months("2025.01.01 ~ 2025.09.30") == "2025.07.01 ~ 2025.09.30"
    assert three_months("2025.01.01 ~ 2025.03.31") == "2025.01.01 ~ 2025.03.31"
    assert three_months("2024.10.01 ~ 2025.01.31") == "2024.11.01 ~ 2025.01.31"
    assert three_months("2025.09.30 현재") == "2025.09.30 현재"
    assert three_months(None) is None


async def test_get_disclosure_text_rejects_bad_number(app):
    """숫자 14자리가 아닌 접수번호는 거부한다."""
    with pytest.raises(ValueError):
        await server.get_disclosure_text("1234")


async def test_get_financials_quarter(app):
    """3분기보고서의 계정, 기간 표기, 파생 수치가 녹화본과 맞다."""
    result = await server.get_financials("삼성전자", 2025, 3)
    assert_envelope(result)
    data, computed = result["data"], result["computed"]
    assert data["statement"] == "연결재무제표" and data["period_type"] == "quarter"
    assert data["currency"] == "KRW" and data["rcept_no"] == "20251114002447"
    assert data["accounts"]["revenue"] == {
        "label": "매출액",
        "current": 86_061_747_000_000,
        # 실제 응답의 기간 표기는 누적 구간(01.01 ~ 09.30)이고 금액은 3개월분이다
        "current_period": "2025.07.01 ~ 2025.09.30",
        "prior": 79_098_731_000_000,
        "prior_period": "2024.07.01 ~ 2024.09.30",
        "cumulative": 239_768_567_000_000,
        "prior_cumulative": 225_082_634_000_000,
    }
    assert data["accounts"]["operating_income"]["current"] == 12_166_062_000_000
    assert data["accounts"]["net_income"]["label"] == "당기순이익(손실)"
    assert data["accounts"]["net_income"]["current"] == 12_225_747_000_000
    assert data["accounts"]["total_assets"]["current"] == 523_659_586_000_000
    assert data["accounts"]["total_assets"]["current_period"] == "2025.09.30 현재"
    assert data["accounts"]["total_assets"]["prior_period"] == "2024.12.31 현재"
    assert data["accounts"]["total_liabilities"]["current"] == 110_158_092_000_000
    assert data["accounts"]["total_equity"]["current"] == 413_501_494_000_000
    assert computed["revenue_change_pct"] == 8.8
    assert computed["revenue_cumulative_change_pct"] == 6.52
    assert computed["operating_income_change_pct"] == 32.48
    assert computed["operating_income_cumulative_change_pct"] == -10.31
    assert computed["net_income_change_pct"] == 21.04
    assert computed["operating_margin_pct"] == 14.14
    assert computed["net_margin_pct"] == 14.21
    assert computed["debt_to_equity_pct"] == 26.64
    assert computed["total_assets_change_pct"] == 1.77
    assert computed["total_liabilities_change_pct"] == -1.94
    assert result["warnings"] == []
    assert result["as_of"] == "2025-09-30"


async def test_get_financials_first_quarter(app):
    """1분기는 3개월 금액과 누적 금액이 같다."""
    result = await server.get_financials("삼성전자", 2025, 1)
    data, computed = result["data"], result["computed"]
    assert data["report"] == "1분기보고서" and data["rcept_no"] == "20250515001922"
    revenue = data["accounts"]["revenue"]
    # 1분기는 3개월 금액과 누적 금액이 같다
    assert revenue["current"] == revenue["cumulative"] == 79_140_503_000_000
    assert revenue["current_period"] == "2025.01.01 ~ 2025.03.31"
    assert revenue["prior_period"] == "2024.01.01 ~ 2024.03.31"
    assert computed["revenue_change_pct"] == computed["revenue_cumulative_change_pct"] == 10.05
    assert computed["operating_income_change_pct"] == 1.2
    assert computed["operating_margin_pct"] == 8.45
    assert computed["total_assets_change_pct"] == 0.36
    assert result["as_of"] == "2025-03-31"


async def test_get_financials_half_year(app):
    """반기보고서의 current는 2분기 석 달 금액이고 cumulative는 상반기 누적이다."""
    result = await server.get_financials("삼성전자", 2025, 2)
    data, computed = result["data"], result["computed"]
    assert data["report"] == "반기보고서" and data["period_type"] == "quarter"
    revenue = data["accounts"]["revenue"]
    # 반기보고서도 기간 표기는 누적(01.01 ~ 06.30)이고 current는 2분기 석 달 금액이다
    assert revenue["current"] == 74_566_317_000_000
    assert revenue["cumulative"] == 153_706_820_000_000
    assert revenue["current_period"] == "2025.04.01 ~ 2025.06.30"
    assert revenue["prior_period"] == "2024.04.01 ~ 2024.06.30"
    assert computed["revenue_change_pct"] == 0.67
    assert computed["revenue_cumulative_change_pct"] == 5.29
    assert computed["operating_income_change_pct"] == -55.23
    assert computed["operating_income_cumulative_change_pct"] == -33.36
    assert computed["net_income_change_pct"] == -48.01
    assert computed["debt_to_equity_pct"] == 26.36
    assert result["as_of"] == "2025-06-30"


async def test_get_financials_annual(app):
    """사업보고서는 연간 금액이고 누적 금액과 누적 증감률이 없다."""
    result = await server.get_financials("삼성전자", 2024)
    data, computed = result["data"], result["computed"]
    assert data["report"] == "사업보고서" and data["period_type"] == "annual"
    assert data["quarter"] == 4 and data["rcept_no"] == "20250311001085"
    assert data["accounts"]["revenue"] == {
        "label": "매출액",
        "current": 300_870_903_000_000,
        "current_period": "2024.01.01 ~ 2024.12.31",
        "prior": 258_935_494_000_000,
        "prior_period": "2023.01.01 ~ 2023.12.31",
        # 사업보고서에는 누적 금액 필드가 없다
        "cumulative": None,
        "prior_cumulative": None,
    }
    assert data["accounts"]["total_equity"]["prior_period"] == "2023.12.31 현재"
    assert computed["revenue_change_pct"] == 16.2
    assert computed["operating_income_change_pct"] == 398.34
    assert computed["net_income_change_pct"] == 122.45
    assert computed["operating_margin_pct"] == 10.88
    assert computed["debt_to_equity_pct"] == 27.93
    assert computed["total_equity_change_pct"] == 10.59
    assert "revenue_cumulative_change_pct" not in computed
    assert result["warnings"] == [] and result["as_of"] == "2024-12-31"


async def test_get_financials_skips_change_when_prior_is_a_loss(app, api):
    """비교 금액이 적자면 그 계정의 증감률만 내지 않고 경고한다."""
    payload = json.loads((FIXTURES / "dart_financials.json").read_text(encoding="utf-8"))
    for row in payload["list"]:
        if row["account_nm"].startswith("당기순이익"):
            row["frmtrm_amount"] = "-1,000,000"
    api.overrides["fnlttSinglAcnt"] = httpx.Response(200, json=payload)
    result = await server.get_financials("삼성전자", 2025, 3)
    # 전년 동기가 적자면 증감률을 내지 않는다
    assert result["computed"]["net_income_change_pct"] is None
    assert result["computed"]["revenue_change_pct"] == 8.8
    assert any("0 이하" in w for w in result["warnings"])


async def test_get_financials_falls_back_to_separate_and_missing(app, api):
    """연결재무제표가 없으면 별도 기준으로 답하고, 자료가 없으면 NotFoundError."""
    payload = json.loads((FIXTURES / "dart_financials.json").read_text(encoding="utf-8"))
    payload["list"] = [r for r in payload["list"] if r["fs_div"] == "OFS"]
    api.overrides["fnlttSinglAcnt"] = httpx.Response(200, json=payload)
    result = await server.get_financials("005930", 2025, 3)
    assert result["data"]["statement"] == "재무제표"
    assert result["data"]["accounts"]["revenue"]["current"] == 62_799_068_000_000
    assert any("별도" in w for w in result["warnings"])

    api.overrides["fnlttSinglAcnt"] = httpx.Response(200, json={"status": "013", "message": "-"})
    with pytest.raises(NotFoundError):
        await server.get_financials("005930", 2027, 1)


async def test_get_stock_prices(app, api):
    """시세를 날짜 오름차순으로 돌려주고 기간 요약을 계산한다."""
    result = await server.get_stock_prices("삼성전자", "2024-11-08", "2024-11-14")
    assert_envelope(result)
    data = result["data"]
    assert (data["short_code"], data["name"]) == ("005930", "삼성전자")
    assert (data["isin"], data["market"]) == ("KR7005930003", "KOSPI")
    prices = data["prices"]
    # 실제 응답처럼 최신순으로 오고, 도구는 날짜 오름차순으로 돌려준다
    assert [p["date"] for p in prices] == [
        "2024-11-08", "2024-11-11", "2024-11-12", "2024-11-13", "2024-11-14",
    ]  # fmt: skip
    assert prices[-1] == {
        "date": "2024-11-14", "open": 53500, "high": 56000, "low": 53000, "close": 55000,
        "volume": 1800000, "trading_value": 99000000000, "change": 1500, "change_pct": 2.8,
        "market_cap": 330000000000000,
    }  # fmt: skip
    # 실제 응답의 등락률은 '-.79'처럼 앞자리 0 없이 온다
    assert prices[0]["change_pct"] == -0.79
    computed = result["computed"]
    assert (computed["start_close"], computed["end_close"]) == (50000, 55000)
    # (55000 - 50000) / 50000 = 10%
    assert computed["period_return_pct"] == 10.0
    # 닷새 거래량 합 7,500,000주 / 5
    assert computed["trading_days"] == 5 and computed["average_volume"] == 1_500_000
    assert (computed["period_high"], computed["period_high_date"]) == (56000, "2024-11-14")
    assert (computed["period_low"], computed["period_low_date"]) == (49500, "2024-11-08")
    # 일간 수익률 4개(4%, -1.92%, 4.9%, 2.8%)의 표본 표준편차
    assert computed["daily_return_stdev_pct"] == 3.04
    assert result["as_of"] == "2024-11-14" and result["source"].endswith("주식시세정보")
    params = next(r for r in api.calls if r.url.path.endswith("/getStockPriceInfo_V2")).url.params
    # endBasDt는 미만 조건이라 하루 뒤를 보낸다
    assert (params["beginBasDt"], params["endBasDt"]) == ("20241108", "20241115")
    assert (params["likeSrtnCd"], params["resultType"]) == ("005930", "json")


async def test_get_stock_prices_drops_other_codes(app, api):
    """likeSrtnCd는 부분 일치라 다른 종목이 섞일 수 있다. 코드가 정확히 같은 행만 쓴다."""
    payload = json.loads((FIXTURES / "fsc_prices.json").read_text(encoding="utf-8"))
    rows = payload["response"]["body"]["items"]["item"]
    rows.append({**rows[0], "srtnCd": "0059301", "itmsNm": "다른종목", "clpr": "1"})
    payload["response"]["body"]["totalCount"] = len(rows)
    api.overrides["getStockPriceInfo"] = httpx.Response(200, json=payload)
    result = await server.get_stock_prices("005930", "2024-11-08", "2024-11-14")
    assert result["computed"]["trading_days"] == 5
    assert result["computed"]["end_close"] == 55000
    assert result["data"]["name"] == "삼성전자"


async def test_prices_are_cached_for_the_day(app, api):
    """같은 조회를 다시 하면 API를 부르지 않고 캐시에서 읽는다."""
    first = await server.get_stock_prices("005930", "2024-11-08", "2024-11-14")
    second = await server.get_stock_prices("005930", "2024-11-08", "2024-11-14")
    assert api.count("getStockPriceInfo") == 1
    assert (first["cached"], second["cached"]) == (False, True)
    assert second["fetched_at"] == first["fetched_at"]


async def test_missing_keys(make_app):
    """키가 없으면 어떤 환경변수가 필요한지 알려 준다."""
    make_app(dart_key=None, fsc_key=None)
    with pytest.raises(MissingKeyError, match="DART_API_KEY"):
        await server.get_financials("005930", 2025, 3)
    with pytest.raises(MissingKeyError, match="DATA_GO_KR_KEY"):
        await server.get_stock_prices("005930")


async def test_unknown_company_suggests_candidates(app):
    """회사를 찾지 못하면 이름이 비슷한 상장사를 알려 준다."""
    with pytest.raises(NotFoundError, match="삼성SDI"):
        await server.list_disclosures("삼성S")


async def test_source_errors_do_not_leak_keys(app, api):
    """소스 오류의 사유는 전달하되 메시지에 API 키를 싣지 않는다."""
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
    # 실제로 받은 형식: 등록되지 않은 키는 HTTP 403에 JSON으로 온다
    api.overrides["getStockPriceInfo"] = httpx.Response(
        403,
        json={
            "OpenAPI_ServiceResponse": {
                "cmmMsgHeader": {
                    "errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
                    "returnAuthMsg": "등록되지 않은 서비스키",
                    "returnReasonCode": "30",
                }
            }
        },
    )
    with pytest.raises(SourceError, match="SERVICE_KEY_IS_NOT_REGISTERED_ERROR"):
        await server.get_stock_prices("005930")
    api.overrides["corpCode"] = httpx.Response(503)
    get_app().cache.set("dart:corp_index", None, -1)
    with pytest.raises(SourceError, match="HTTP 503") as http_error:
        await server.get_financials("005930", 2025, 3)
    assert api.count("corpCode") == 4  # 처음 1번 + 재시도 3번
    for error in (dart_error, fsc_error, http_error):
        assert "test-dart-key" not in str(error.value)
        assert "test-fsc-key" not in str(error.value)


async def test_no_solicitation_wording_in_structured_output(app):
    """본문 텍스트를 뺀 도구 응답에 투자 권유 표현이 섞이지 않는다."""
    outputs = [
        await server.resolve_ticker("삼성전자"),
        await server.list_disclosures("삼성전자", limit=20),
        await server.get_financials("삼성전자", 2025, 3),
        await server.get_stock_prices("삼성전자", "2024-11-08", "2024-11-14"),
    ]
    blob = json.dumps(outputs, ensure_ascii=False)
    for word in ("매수", "매도", "목표가", "추천"):
        assert word not in blob


async def test_every_tool_response_carries_a_citation(app):
    """도구 5개의 응답 모두에 출처와 기준일을 합친 인용 문구가 들어 있다."""
    results = [
        await server.resolve_ticker("삼성전자"),
        await server.list_disclosures("삼성전자", limit=20),
        await server.get_disclosure_text("20261118000151"),
        await server.get_financials("삼성전자", 2025, 3),
        await server.get_stock_prices("삼성전자", "2024-11-08", "2024-11-14"),
    ]
    for result in results:
        assert_envelope(result)
    assert results[3]["citation"] == (
        "출처: DART OpenAPI (금융감독원 전자공시시스템) · 기준일: 2025-09-30"
    )
    assert results[4]["citation"] == (
        "출처: 공공데이터포털 금융위원회_주식시세정보 · 기준일: 2024-11-14"
    )


async def test_tool_descriptions_ask_for_the_citation():
    """모델이 읽는 도구 설명마다 인용 문구를 답변에 적으라는 지시가 있다."""
    for tool in await server.mcp.list_tools():
        assert "citation" in tool.description, tool.name


async def test_tools_are_registered_with_mcp():
    """도구 5개가 등록돼 있고 필수 인자가 스키마에 드러난다."""
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
    """키가 든 요청 URL이 로그에 남지 않는다."""
    with caplog.at_level(logging.INFO):
        await server.list_disclosures("005930", limit=20)
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
