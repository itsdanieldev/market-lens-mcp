"""환경변수(.env) 설정 로딩."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from dotenv import find_dotenv, load_dotenv


@dataclass(frozen=True)
class Settings:
    """실행 설정.

    Attributes:
        dart_api_key: DART 인증키. 없으면 None.
        data_go_kr_key: 공공데이터포털 인증키(디코딩된 값). 없으면 None.
        cache_path: SQLite 캐시 파일 경로.
    """

    dart_api_key: str | None
    data_go_kr_key: str | None
    cache_path: Path


def load_settings() -> Settings:
    """환경변수에서 설정을 읽는다.

    .env가 있으면 먼저 불러오되 이미 있는 환경변수는 덮어쓰지 않는다.
    공공데이터포털의 Encoding 키('%'가 들어 있음)는 디코딩해 둔다.

    Returns:
        읽은 설정. 비어 있는 키는 None.
    """
    load_dotenv(find_dotenv(usecwd=True))
    cache_dir = Path(
        os.environ.get("MARKET_LENS_CACHE_DIR") or Path.home() / ".cache" / "market-lens"
    )
    data_key = (os.environ.get("DATA_GO_KR_KEY") or "").strip() or None
    if data_key and "%" in data_key:
        # 포털의 Encoding 키를 넣은 경우: httpx가 다시 인코딩하므로 먼저 풀어 둔다.
        data_key = unquote(data_key)
    return Settings(
        dart_api_key=(os.environ.get("DART_API_KEY") or "").strip() or None,
        data_go_kr_key=data_key,
        cache_path=cache_dir / "cache.sqlite3",
    )
