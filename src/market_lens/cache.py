"""SQLite TTL 캐시.

시세는 당일(KST 자정)까지, 공시 본문·재무제표는 장기 보관해 API 호출 한도를 아낀다.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .util import KST

HOUR = 3600
DAY = 24 * HOUR

TTL_DISCLOSURE_LIST = HOUR  # 새 공시가 수시로 올라온다
TTL_REFERENCE = DAY  # 상장종목 목록, DART 고유번호
TTL_LONG = 30 * DAY  # 공시 본문, 재무제표


def seconds_until_kst_midnight(now: float | None = None) -> int:
    """다음 KST 자정까지 남은 초를 계산한다(시세 캐시의 유효 기간).

    Args:
        now: 기준 시각(epoch 초). 생략하면 현재 시각.

    Returns:
        남은 초. 최소 1.
    """
    current = datetime.fromtimestamp(time.time() if now is None else now, KST)
    midnight = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - current).total_seconds()))


@dataclass(frozen=True)
class CacheHit:
    """캐시에서 읽은 값.

    Attributes:
        value: 저장했던 값.
        stored_at: 값을 저장한 시각(epoch 초).
    """

    value: Any
    stored_at: float


class Cache:
    """키·값·만료 시각을 SQLite 테이블 하나에 두는 TTL 캐시.

    값은 JSON으로 저장하므로 JSON으로 바꿀 수 있는 값만 넣는다.

    Attributes:
        now: 현재 시각(epoch 초)을 돌려주는 함수.
    """

    def __init__(self, path: Path | str, clock: Callable[[], float] = time.time):
        """DB를 열고 만료된 항목을 지운다.

        Args:
            path: DB 파일 경로. 상위 폴더가 없으면 만든다. ":memory:"면 메모리 DB.
            clock: 현재 시각(epoch 초)을 돌려주는 함수. 테스트에서 시각을 바꿀 때 쓴다.
        """
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.now = clock
        self._db = sqlite3.connect(str(path))
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL, "
            "stored_at REAL NOT NULL, expires_at REAL NOT NULL)"
        )
        # 만료된 항목은 읽을 때 걸러지지만 파일에 계속 남으므로, 열 때 한 번 치운다.
        self._db.execute("DELETE FROM cache WHERE expires_at <= ?", (self.now(),))
        self._db.commit()

    def get(self, key: str) -> CacheHit | None:
        """만료되지 않은 값을 읽는다.

        Args:
            key: 캐시 키.

        Returns:
            값과 저장 시각. 없거나 만료됐으면 None.
        """
        row = self._db.execute(
            "SELECT value, stored_at FROM cache WHERE key = ? AND expires_at > ?",
            (key, self.now()),
        ).fetchone()
        return CacheHit(json.loads(row[0]), row[1]) if row else None

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        """값을 저장한다. 같은 키가 있으면 덮어쓴다.

        Args:
            key: 캐시 키.
            value: JSON으로 바꿀 수 있는 값.
            ttl_seconds: 유효 기간(초).
        """
        now = self.now()
        self._db.execute(
            "INSERT OR REPLACE INTO cache (key, value, stored_at, expires_at) VALUES (?, ?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), now, now + ttl_seconds),
        )
        self._db.commit()

    def close(self) -> None:
        """DB 연결을 닫는다."""
        self._db.close()
