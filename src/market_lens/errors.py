"""도구가 사용자에게 그대로 보여 주는 오류. 메시지에 API 키나 요청 URL을 넣지 않는다.

MCP SDK 2.x는 ToolError의 메시지만 모델에게 전달하고, 그 밖의 예외는
"Error executing tool <name>"으로 가린다. 그래서 안내가 필요한 오류는 모두 ToolError를 상속한다.
"""

from mcp.server.mcpserver.exceptions import ToolError


class MarketLensError(ToolError):
    """이 서버가 던지는 오류의 공통 부모. 메시지가 모델에게 그대로 전달된다."""


class InvalidInputError(MarketLensError, ValueError):
    """도구 인자가 잘못됨(날짜 형식, 공시유형, 접수번호 등)."""


class MissingKeyError(MarketLensError):
    """필요한 API 키의 환경변수가 없음. 메시지에 발급받을 곳을 안내한다."""

    def __init__(self, env_name: str, where: str):
        """env_name은 환경변수 이름, where는 키를 발급받는 주소."""
        super().__init__(
            f"{env_name} 환경변수가 없습니다. {where}에서 키를 발급받아 .env에 넣어 주세요."
        )


class SourceError(MarketLensError):
    """데이터 소스가 오류를 돌려줬거나 응답을 해석할 수 없음."""


class NotFoundError(MarketLensError):
    """요청한 회사, 종목, 자료가 소스에 없음."""
