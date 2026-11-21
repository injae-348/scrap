"""AI 요청 제한 (docs/API.md v1.5·v1.6 "AI 요청 제한"). `/ai/extract`·`/ai/search` 합산, IP 무관.

- 분당 `per_minute`회 (최근 60초, 서버 메모리)
- 하루 `per_day`회 (Asia/Seoul 날짜, DB `ai_usage_days.count` — 재시작 후에도 유지)
- 하루 토큰 예산 `tokens_per_day` (Asia/Seoul 날짜, DB `ai_usage_days.tokens`). Claude 응답의
  `usage` 합계를 응답을 받을 때마다 `add_tokens()`로 누적하고, 요청 시작(`begin()`)과 AI 검색의
  매 Claude 호출 직전(`check_tokens()`)에 누적량이 예산 이상이면 `AiTokenBudgetExceeded`.
  요청 하나가 예산을 넘겨도 이미 받은 응답의 사용량은 그대로 누적한다 (다음 확인에서 막힌다).
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
from app.config import DEFAULT_AI_TOKENS_PER_DAY
from app.db import transaction

WINDOW_SECONDS = 60
DEFAULT_MAX_CONCURRENT = 2
# 동시 처리 자리가 없을 때 다시 시도할 때까지 (AI 요청은 보통 수십 초 걸린다).
BUSY_RETRY_AFTER = 5


class AiLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(retry_after)
        self.retry_after = retry_after


class AiDailyLimitExceeded(AiLimitExceeded):
    """오늘(Asia/Seoul) 요청 횟수를 다 썼다. `retry_after`는 다음 자정까지 남은 초."""


class AiTokenBudgetExceeded(AiLimitExceeded):
    """오늘(Asia/Seoul) 토큰 예산을 다 썼다. `retry_after`는 다음 자정까지 남은 초."""


# usage 항목 (docs/API.md v1.6). 값 하나의 상한은 이상한 응답이 기록을 망가뜨리지 않게 둔다.
USAGE_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)
_USAGE_VALUE_MAX = 1_000_000_000


def response_tokens(response: object) -> int:
    """Claude 응답의 `usage` 합계. usage가 없거나 값이 정수가 아니면 그 항목은 0으로 본다."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0
    total = 0
    for name in USAGE_FIELDS:
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            total += min(value, _USAGE_VALUE_MAX)
    return total


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
        tokens_per_day: int = DEFAULT_AI_TOKENS_PER_DAY,
    ) -> None:
        self._clock = clock
        self._connect = connect
        self.per_minute = per_minute
        self.per_day = per_day
        self.tokens_per_day = tokens_per_day
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
            count, tokens = self._day_usage(kst_day(now))
            if count + self._reserved >= self.per_day:
                raise AiDailyLimitExceeded(seconds_until_next_day(now))
            if tokens >= self.tokens_per_day:
                raise AiTokenBudgetExceeded(seconds_until_next_day(now))
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

    # DB 조회가 있으므로 스레드풀에서 부른다.
    def check_tokens(self) -> None:
        """Claude 호출 직전: 오늘 누적 토큰이 예산 이상이면 `AiTokenBudgetExceeded`."""
        now = self._clock.now()
        _, tokens = self._day_usage(kst_day(now))
        if tokens >= self.tokens_per_day:
            raise AiTokenBudgetExceeded(seconds_until_next_day(now))

    def add_tokens(self, tokens: int) -> None:
        """Claude 응답을 받은 직후: 그 응답의 사용량을 오늘 날짜에 더한다 (0이면 쓰지 않는다)."""
        if tokens <= 0:
            return
        day = kst_day(self._clock.now())
        conn = self._connect()
        try:
            with transaction(conn):
                conn.execute(
                    "INSERT INTO ai_usage_days (day, count, tokens) VALUES (?, 0, ?)"
                    " ON CONFLICT (day) DO UPDATE SET tokens = tokens + excluded.tokens",
                    (day, tokens),
                )
        finally:
            conn.close()

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

    def _day_usage(self, day: str) -> tuple[int, int]:
        """(요청 수, 토큰 수)."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT count, tokens FROM ai_usage_days WHERE day = ?", (day,)
            ).fetchone()
        finally:
            conn.close()
        return (int(row[0]), int(row[1])) if row else (0, 0)
