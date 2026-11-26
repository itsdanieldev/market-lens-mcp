"""market-lens MCP 서버: 한국 주식 리서치 도구 5개.

여기서는 도구의 이름, 인자, 설명만 정의하고 처리는 services에 맡긴다.
모든 도구는 source, as_of가 붙은 공통 형식(models.Envelope)으로 응답한다.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from . import __version__
from .app import get_app
from .services import disclosures, financials, prices, tickers

INSTRUCTIONS = """\
한국 상장사의 공시, 재무제표, 주가를 공식 API(DART, 공공데이터포털 금융위원회)로 조회하는 \
리서치 도구입니다.

답변 규칙:
- 사실 정리와 설명만 합니다. 매수·매도 의견, 목표가, 종목 추천 같은 투자 권유 표현은 쓰지 않습니다.
- 답변의 숫자는 도구 응답 값만 인용합니다. 수익률·증감률은 직접 계산하지 말고 computed 필드를 씁니다.
- 답변 끝에 각 도구 응답의 citation(출처·기준일)을 그대로 적습니다. 도구를 여러 개 썼으면 모두 적습니다.
- 주가는 전 영업일 종가 기준이며 실시간이 아닙니다.

종목 브리핑 순서 예: resolve_ticker → get_financials → list_disclosures →
(필요하면) get_disclosure_text → get_stock_prices.
"""

MAX_TEXT_CHARS = 50_000

mcp = MCPServer("market-lens", instructions=INSTRUCTIONS, version=__version__)

# 아래 도구 함수의 docstring은 MCP 클라이언트를 거쳐 모델이 읽는 도구 설명으로 통째로 전달된다.
# 그래서 Args/Returns 절을 두지 않고 모델이 알아야 할 내용만 적는다. 인자 설명은
# Field(description=...)에 적으면 도구의 입력 스키마로 전달된다.
# 서버 안내문(INSTRUCTIONS)은 클라이언트에 따라 모델에게 덜 반영될 수 있어,
# 출처·기준일을 적으라는 지시는 도구 설명마다 다시 적는다.


@mcp.tool()
async def resolve_ticker(
    query: Annotated[
        str, Field(description="종목명(예: 삼성전자) 또는 6자리 종목코드(예: 005930)")
    ],
) -> dict[str, Any]:
    """종목명이나 종목코드를 단축코드, ISIN, DART corp_code, 시장으로 바꾼다.

    하나로 확정되면 match에, 여러 개가 걸리면 candidates에 담는다.
    답변 끝에 응답의 citation(출처·기준일)을 그대로 적는다.
    """
    app = get_app()
    return await tickers.resolve(query, dart=app.dart_or_none, fsc=app.fsc_or_none)


@mcp.tool()
async def list_disclosures(
    ticker: Annotated[str, Field(description="종목명 또는 6자리 종목코드")],
    start_date: Annotated[
        str | None, Field(description="시작일 YYYY-MM-DD. 생략하면 종료일 30일 전")
    ] = None,
    end_date: Annotated[str | None, Field(description="종료일 YYYY-MM-DD. 생략하면 오늘")] = None,
    disclosure_type: Annotated[
        str | None,
        Field(
            description="공시유형 코드 또는 이름: A 정기공시, B 주요사항보고, C 발행공시, D 지분공시, "
            "E 기타공시, F 외부감사관련, G 펀드공시, H 자산유동화, I 거래소공시, J 공정위공시"
        ),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=200, description="최대 건수")] = 30,
) -> dict[str, Any]:
    """기간 안의 DART 공시 목록을 최신순으로 돌려준다(제목, 접수일, 접수번호).

    답변 끝에 응답의 citation(출처·기준일)을 그대로 적는다.
    """
    return await disclosures.list_disclosures(
        get_app().dart, ticker, start_date, end_date, disclosure_type, limit
    )


@mcp.tool()
async def get_disclosure_text(
    rcept_no: Annotated[str, Field(description="접수번호 14자리(list_disclosures의 rcept_no)")],
    max_chars: Annotated[
        int, Field(ge=500, le=MAX_TEXT_CHARS, description="돌려줄 최대 글자 수")
    ] = 8000,
    offset: Annotated[int, Field(ge=0, description="이어 읽을 시작 위치(글자)")] = 0,
) -> dict[str, Any]:
    """공시 원문의 본문 텍스트를 돌려준다. 길면 잘라서 주고 next_offset으로 이어 읽는다.

    답변 끝에 응답의 citation(출처·기준일)을 그대로 적는다.
    """
    return await disclosures.disclosure_text(get_app().dart, rcept_no, max_chars, offset)


@mcp.tool()
async def get_financials(
    ticker: Annotated[str, Field(description="종목명 또는 6자리 종목코드")],
    year: Annotated[int, Field(ge=2015, description="사업연도(2015년 이후)")],
    quarter: Annotated[
        int, Field(ge=1, le=4, description="1~3은 해당 분기 보고서, 4는 사업보고서(연간 실적)")
    ] = 4,
) -> dict[str, Any]:
    """매출, 영업이익, 순이익, 자산, 부채, 자본과 증감률·이익률·부채비율을 돌려준다.

    금액 단위는 원. 연결재무제표가 있으면 연결, 없으면 별도 기준이다.
    분기(1~3)의 손익 항목 current는 3개월 금액이고 cumulative는 연초부터의 누적이다.
    quarter=4는 4분기 석 달이 아니라 연간 금액이다.
    답변 끝에 응답의 citation(출처·기준일)을 그대로 적는다.
    """
    return await financials.get_financials(get_app().dart, ticker, year, quarter)


@mcp.tool()
async def get_stock_prices(
    ticker: Annotated[str, Field(description="종목명 또는 6자리 종목코드")],
    start_date: Annotated[
        str | None, Field(description="시작일 YYYY-MM-DD. 생략하면 종료일 90일 전")
    ] = None,
    end_date: Annotated[str | None, Field(description="종료일 YYYY-MM-DD. 생략하면 오늘")] = None,
) -> dict[str, Any]:
    """일별 시가·고가·저가·종가·거래량(OHLCV)과 기간 수익률 요약을 돌려준다.

    전 영업일 종가까지 제공되며 실시간 시세가 아니다. 수정주가가 아니다.
    답변 끝에 응답의 citation(출처·기준일)을 그대로 적는다.
    """
    return await prices.get_stock_prices(get_app().fsc, ticker, start_date, end_date)


def main() -> None:
    """표준 입출력(stdio)으로 MCP 서버를 실행한다. market-lens-mcp 명령의 진입점."""
    mcp.run()


if __name__ == "__main__":
    main()
