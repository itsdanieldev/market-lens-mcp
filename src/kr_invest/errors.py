"""도구가 사용자에게 그대로 보여 주는 오류. 메시지에 API 키나 요청 URL을 넣지 않는다."""


class KrInvestError(Exception):
    pass


class MissingKeyError(KrInvestError):
    def __init__(self, env_name: str, where: str):
        super().__init__(
            f"{env_name} 환경변수가 없습니다. {where}에서 키를 발급받아 .env에 넣어 주세요."
        )


class SourceError(KrInvestError):
    """데이터 소스가 오류를 돌려줬거나 응답을 해석할 수 없음."""


class NotFoundError(KrInvestError):
    pass
