"""AI 요청 제한 (docs/API.md v1.5 "AI 요청 제한"). `/ai/extract`·`/ai/search` 합산, IP 무관.

- 분당 `per_minute`회 (최근 60초, 서버 메모리)
- 하루 `per_day`회 (Asia/Seoul 날짜, DB `ai_usage_days` — 재시작 후에도 유지)
- 동시 처리 `max_concurrent`개

흐름: `begin()`(입력 검사·사용 가능 확인 뒤) → Claude를 부르기 직전 `commit()` → 끝나면 `finish()`.
- `begin()`은 동시 처리 자리와 횟수 자리 하나를 **예약**한다. 예약은 상한 계산에 들어가므로
  동시에 들어온 요청이 함께 상한을 넘지 못한다. 넘으면 `AiLimitExceeded(retry_after)`.
- `commit()`에서야 실제 횟수로 센다 (Claude를 부르기 전에 끝난 요청 — 본문을 얻지 못한 AI 채우기 —
  은 세지 않는다). Claude가 실패·거부해도 이미 불렀으므로 센다.
- `finish()`는 동시 처리 자리와 (세지 않은) 예약을 돌려준다.

진행 중 예약·분당 기록은 프로세스 메모리에 있으므로 워커 1개를 전제로 한다.
"""

import math
import sqlite3
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.clock import KST, Clock
from app.db import transaction

WINDOW_SECONDS = 60
DEFAULT_MAX_CONCURRENT = 2
# 동시 처리 자리가 없을 때 다시 시도할 때까지 (AI 요청은 보통 수십 초 걸린다).
BUSY_RETRY_AFTER = 5


class AiLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(retry_after)
        self.retry_after = retry_after


@dataclass
class AiTicket:
    committed: bool = False
    finished: bool = False


def kst_day(ts: float) -> str:
    return datetime.fromtimestamp(ts, KST).date().isoformat()


def seconds_until_next_day(ts: float) -> int:
    now = datetime.fromtimestamp(ts, KST)
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), KST)
    return max(1, math.ceil((tomorrow - now).total_seconds()))


class AiRequestLimiter:
    def __init__(
        self,
        clock: Clock,
        connect: Callable[[], sqlite3.Connection],
        per_minute: int,
        per_day: int,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
    ) -> None:
        self._clock = clock
        self._connect = connect
        self.per_minute = per_minute
        self.per_day = per_day
        self.max_concurrent = max_concurrent
        self._lock = threading.Lock()
        self._minute: deque[float] = deque()  # 최근 60초 안에 센 시각
        self._active = 0  # 처리 중 (동시 처리 자리)
        self._reserved = 0  # 처리 중이지만 아직 세지 않은 것

    # DB 조회가 있으므로 스레드풀에서 부른다.
    def begin(self) -> AiTicket:
        now = self._clock.now()
        with self._lock:
            self._purge(now)
            if len(self._minute) + self._reserved >= self.per_minute:
                oldest = self._minute[0] if self._minute else now
                raise AiLimitExceeded(max(1, math.ceil(oldest + WINDOW_SECONDS - now)))
            if self._day_count(kst_day(now)) + self._reserved >= self.per_day:
                raise AiLimitExceeded(seconds_until_next_day(now))
            if self._active >= self.max_concurrent:
                raise AiLimitExceeded(BUSY_RETRY_AFTER)
            self._active += 1
            self._reserved += 1
            return AiTicket()

    def commit(self, ticket: AiTicket) -> None:
        """Claude를 부르기 직전: 이 요청을 분·하루 횟수에 넣는다."""
        if ticket.committed or ticket.finished:
            return
        now = self._clock.now()
        with self._lock:
            conn = self._connect()
            try:
                with transaction(conn):
                    conn.execute(
                        "INSERT INTO ai_usage_days (day, count) VALUES (?, 1)"
                        " ON CONFLICT (day) DO UPDATE SET count = count + 1",
                        (kst_day(now),),
                    )
            finally:
                conn.close()
            self._minute.append(now)
            self._reserved -= 1
            ticket.committed = True

    def finish(self, ticket: AiTicket) -> None:
        if ticket.finished:
            return
        with self._lock:
            ticket.finished = True
            self._active -= 1
            if not ticket.committed:
                self._reserved -= 1

    def clear(self) -> None:
        """메모리 기록만 지운다 (테스트용)."""
        with self._lock:
            self._minute.clear()

    def _purge(self, now: float) -> None:
        while self._minute and now - self._minute[0] >= WINDOW_SECONDS:
            self._minute.popleft()

    def _day_count(self, day: str) -> int:
        conn = self._connect()
        try:
            row = conn.execute("SELECT count FROM ai_usage_days WHERE day = ?", (day,)).fetchone()
        finally:
            conn.close()
        return int(row[0]) if row else 0
