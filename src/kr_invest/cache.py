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
    """시세 캐시용: 지금부터 다음 KST 자정까지 남은 초."""
    current = datetime.fromtimestamp(time.time() if now is None else now, KST)
    midnight = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - current).total_seconds()))


@dataclass(frozen=True)
class CacheHit:
    value: Any
    stored_at: float


class Cache:
    def __init__(self, path: Path | str, clock: Callable[[], float] = time.time):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.now = clock
        self._db = sqlite3.connect(str(path))
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL, "
            "stored_at REAL NOT NULL, expires_at REAL NOT NULL)"
        )
        self._db.execute("DELETE FROM cache WHERE expires_at <= ?", (self.now(),))
        self._db.commit()

    def get(self, key: str) -> CacheHit | None:
        row = self._db.execute(
            "SELECT value, stored_at FROM cache WHERE key = ? AND expires_at > ?",
            (key, self.now()),
        ).fetchone()
        return CacheHit(json.loads(row[0]), row[1]) if row else None

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        now = self.now()
        self._db.execute(
            "INSERT OR REPLACE INTO cache (key, value, stored_at, expires_at) VALUES (?, ?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), now, now + ttl_seconds),
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()
