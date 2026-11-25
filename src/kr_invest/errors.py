"""도구가 사용자에게 그대로 보여 주는 오류. 메시지에 API 키나 요청 URL을 넣지 않는다.

MCP SDK 2.x는 ToolError의 메시지만 모델에게 전달하고, 그 밖의 예외는
"Error executing tool <name>"으로 가린다. 그래서 안내가 필요한 오류는 모두 ToolError를 상속한다.
"""

from mcp.server.mcpserver.exceptions import ToolError


class KrInvestError(ToolError):
    pass


class InvalidInputError(KrInvestError, ValueError):
    """도구 인자가 잘못됨(날짜 형식, 공시유형, 접수번호 등)."""


class MissingKeyError(KrInvestError):
    def __init__(self, env_name: str, where: str):
        super().__init__(
            f"{env_name} 환경변수가 없습니다. {where}에서 키를 발급받아 .env에 넣어 주세요."
        )


class SourceError(KrInvestError):
    """데이터 소스가 오류를 돌려줬거나 응답을 해석할 수 없음."""


class NotFoundError(KrInvestError):
    pass
