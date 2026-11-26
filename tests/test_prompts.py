"""MCP 프롬프트가 등록돼 있고 도구 사용과 답변 규칙을 지시하는지 검증한다."""

from __future__ import annotations

import re

from mcp import Client

from market_lens import prompts, server

TOOLS = {
    "resolve_ticker",
    "list_disclosures",
    "get_disclosure_text",
    "get_financials",
    "get_stock_prices",
}


async def test_prompts_are_registered_with_titles_and_arguments():
    """프롬프트 3개가 메뉴에 보일 제목, 설명, 인자와 함께 등록돼 있다."""
    async with Client(server.mcp) as client:
        listed = {p.name: p for p in (await client.list_prompts()).prompts}
    assert set(listed) == {"stock_briefing", "earnings_review", "disclosure_digest"}
    briefing = listed["stock_briefing"]
    assert briefing.title == "종목 브리핑" and briefing.description
    assert [(a.name, a.required) for a in briefing.arguments] == [("company", True)]
    assert [(a.name, a.required) for a in listed["earnings_review"].arguments] == [
        ("company", True),
        ("period", False),
    ]
    assert all(a.description for p in listed.values() for a in p.arguments)


async def test_prompt_is_rendered_through_the_client():
    """클라이언트가 인자를 넣어 요청하면 사용자 메시지 하나로 문구가 온다."""
    async with Client(server.mcp) as client:
        result = await client.get_prompt("stock_briefing", {"company": "삼성전자"})
    assert len(result.messages) == 1 and result.messages[0].role == "user"
    text = result.messages[0].content.text
    assert text.startswith("market-lens 도구로 삼성전자의 종목 브리핑")


def test_briefing_names_every_tool():
    """종목 브리핑은 도구 5개를 모두 이름으로 지시한다."""
    text = prompts.stock_briefing("005930")
    assert all(tool in text for tool in TOOLS)


def test_every_prompt_carries_the_answer_rules():
    """프롬프트마다 도구 값만 쓰기, 투자 권유 금지, 출처 표기 규칙이 들어 있다."""
    texts = [
        prompts.stock_briefing("삼성전자"),
        prompts.earnings_review("삼성전자", "2026년 3분기"),
        prompts.disclosure_digest("삼성전자", "14"),
    ]
    for text in texts:
        assert prompts.RULES in text
        assert "citation" in text and "computed" in text
    # 프롬프트가 지시하는 도구 이름은 실제로 있는 도구여야 한다
    mentioned = {
        name for text in texts for name in re.findall(r"(?:get|list|resolve)_[a-z_]+", text)
    }
    assert mentioned and mentioned <= TOOLS


def test_optional_arguments_fall_back_to_defaults():
    """기간을 비우면 가장 최근 분기를, 일수가 숫자가 아니면 30일을 쓴다."""
    assert "가장 최근 분기 실적" in prompts.earnings_review("삼성전자")
    assert "2025년 연간 실적" in prompts.earnings_review("삼성전자", " 2025년 연간 ")
    assert "최근 30일 공시" in prompts.disclosure_digest("삼성전자", "한 달")
    assert "최근 14일 공시" in prompts.disclosure_digest("삼성전자", "14")
