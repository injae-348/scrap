"""시간 주입용 시계.

인증 만료·요청 제한·TOTP는 모두 이 시계를 통해 현재 시각을 얻는다.
테스트는 가짜 시계(tests/conftest.py `FakeClock`)를 넣어 sleep 없이 시간을 앞당긴다.
"""

import time
from datetime import UTC, datetime, timedelta, timezone

# 서비스 기준 시간대 Asia/Seoul. 1988년 이후 서머타임이 없으므로 고정 오프셋으로 충분하다
# (slim 이미지에 tzdata가 없어도 동작).
KST = timezone(timedelta(hours=9), "Asia/Seoul")


class Clock:
    def now(self) -> float:
        """유닉스 시각(초)."""
        return time.time()


def to_iso(ts: float) -> str:
    """유닉스 시각 → `2026-11-19T17:00:00+09:00` (초 단위, Asia/Seoul)."""
    return datetime.fromtimestamp(int(ts), UTC).astimezone(KST).isoformat()


def from_iso(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()
