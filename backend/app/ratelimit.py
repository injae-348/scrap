"""요청 제한.

- 공통 상한(`RequestRateLimiter` + `RateLimitMiddleware`, 메모리): 모든 `/api/*`(health 포함)에
  IP별 분당 상한. 넘으면 429 `too_many_requests` + `Retry-After`.
- 로그인 실패 제한(`LoginAttemptLimiter`, IP별, 메모리): 비밀번호·TOTP·복구 코드·가입 토큰 실패를
  합쳐 5회 연속 실패하면 15분 잠금. 잠금 중에는 해당 엔드포인트가 429 `too_many_attempts`.
- 계정 단위 2단계 실패 상한(`AccountAttemptLimiter`, 모든 IP 합산, DB): TOTP·복구 코드 실패가
  15분 안에 10회면 15분 동안 `/auth/login/verify` 429.

동시 요청 대책: 실패를 검증이 끝난 뒤에만 세면, 한꺼번에 보낸 요청이 모두 잠금 검사를 통과한다.
그래서 시도를 시작할 때 잠금 아래에서 자리를 **예약**하고(`실패 + 진행 중 >= 상한`이면 거부),
끝날 때 예약을 풀면서 실패를 기록한다 (`begin()`/`finish()`, 라우트에서는 `router._reserve`).
진행 중 시도 수는 프로세스 메모리에 있으므로 워커 1개를 전제로 한다.

클라이언트 IP는 `scope["client"]`(= `request.client.host`)만 쓴다. 프록시 헤더는 uvicorn
`--proxy-headers --forwarded-allow-ips=<web IP>`가 이미 반영했으므로
X-Forwarded-For를 직접 읽지 않는다. 키는 `client_key()`로 정규화한다
(IPv4-mapped IPv6 → IPv4, IPv6 → /64 네트워크).

메모리 저장소는 키 수 상한이 있어 무한히 늘지 않는다.
"""

import ipaddress
import logging
import math
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from starlette.types import ASGIApp, Receive, Scope, Send

from app.clock import Clock
from app.db import transaction
from app.errors import error_response

logger = logging.getLogger("app")

UNKNOWN_CLIENT = "unknown"


def client_key(host: str | None) -> str:
    """요청 제한용 IP 키. IPv4는 주소 하나, IPv6는 /64 단위 (IPv4-mapped는 IPv4로)."""
    if not host:
        return UNKNOWN_CLIENT
    try:
        ip = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return host  # 테스트 클라이언트 이름 등 IP가 아닌 값은 그대로
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network(f"{ip}/64", strict=False))
    return str(ip)


def client_ip_from_scope(scope: Scope) -> str:
    client = scope.get("client")
    return client_key(str(client[0]) if client and client[0] else None)


def is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _looks_like_proxy_misconfig(host: str | None) -> bool:
    """운영에서 클라이언트 IP가 사설 주소면 프록시 헤더 설정이 어긋났을 가능성이 크다."""
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return ip.is_private and not ip.is_loopback


# ── 공통 분당 상한 ────────────────────────────────────


class RequestRateLimiter:
    """IP별 고정 창(60초) 카운터. 반환값이 None이면 허용, 숫자면 Retry-After(초)."""

    WINDOW_SECONDS = 60

    def __init__(self, clock: Clock, limit: int, max_keys: int = 10_000) -> None:
        self._clock = clock
        self.limit = limit
        self.max_keys = max_keys
        # ip → (창 시작 시각, 창 안의 요청 수)
        self._windows: OrderedDict[str, tuple[float, int]] = OrderedDict()
        self._lock = threading.Lock()

    def hit(self, ip: str) -> int | None:
        now = self._clock.now()
        with self._lock:
            start, count = self._windows.get(ip, (now, 0))
            if now - start >= self.WINDOW_SECONDS:
                start, count = now, 0
            count += 1
            self._windows[ip] = (start, count)
            self._windows.move_to_end(ip)
            self._evict(now)
            if count > self.limit:
                return max(1, math.ceil(start + self.WINDOW_SECONDS - now))
            return None

    def clear(self) -> None:
        with self._lock:
            self._windows.clear()

    def _evict(self, now: float) -> None:
        if len(self._windows) <= self.max_keys:
            return
        expired = [k for k, (s, _) in self._windows.items() if now - s >= self.WINDOW_SECONDS]
        for key in expired:
            del self._windows[key]
        while len(self._windows) > self.max_keys:
            self._windows.popitem(last=False)


class RateLimitMiddleware:
    """`/api/*` 요청마다 공통 상한을 검사하는 순수 ASGI 미들웨어.

    `warn_private_clients`(운영)이면, 클라이언트 IP가 사설 주소일 때 프로세스당 한 번 경고한다
    (모든 사용자가 프록시 IP 하나로 묶여 잠금·상한을 함께 쓰는 설정 오류를 빨리 알기 위함).
    """

    def __init__(
        self, app: ASGIApp, limiter: RequestRateLimiter, warn_private_clients: bool = False
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.warn_private_clients = warn_private_clients
        self._warned = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and is_api_path(scope["path"]):
            client = scope.get("client")
            host = str(client[0]) if client and client[0] else None
            if self.warn_private_clients and not self._warned and _looks_like_proxy_misconfig(host):
                self._warned = True
                logger.warning(
                    "클라이언트 IP가 사설 주소로 보입니다. 프록시 헤더 신뢰 설정"
                    "(--forwarded-allow-ips, web 고정 IP)을 확인하세요."
                )
            retry_after = self.limiter.hit(client_key(host))
            if retry_after is not None:
                response = error_response(
                    429,
                    "too_many_requests",
                    "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                    headers={"Retry-After": str(retry_after)},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


# ── 시도 예약 ────────────────────────────────────────


class AttemptRejected(Exception):
    """잠금 중이거나 예약할 자리가 없다. `retry_after`초 뒤에 다시 시도."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(retry_after)
        self.retry_after = retry_after


@dataclass
class AttemptSlot:
    failed: bool = False

    def fail(self) -> None:
        self.failed = True


class ReservingLimiter:
    """키별로 `실패 수 + 진행 중 시도 수`가 상한을 넘지 않게 예약하는 공통 뼈대.

    진행 중 시도 수는 메모리에 둔다 (요청이 끝나면 사라지는 값).
    확정된 실패와 잠금은 하위 클래스가 저장한다 (`_state`, `_add_failure`).
    """

    MAX_FAILURES = 5
    LOCK_SECONDS = 15 * 60

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        # 키 → 진행 중 시도 수. 0이 되면 지우므로 크기는 동시 요청 수를 넘지 않는다.
        self._in_flight: dict[str, int] = {}

    # 하위 클래스가 구현: 잠금 아래에서 호출된다.
    def _state(self, key: str, now: float) -> tuple[int, float]:  # pragma: no cover - 추상
        """(현재 세는 실패 수, 잠금 끝 시각)."""
        raise NotImplementedError

    def _add_failure(self, key: str, now: float) -> None:  # pragma: no cover - 추상
        raise NotImplementedError

    def retry_after(self, key: str) -> int | None:
        """잠겨 있으면 남은 초, 아니면 None."""
        now = self._clock.now()
        with self._lock:
            _, until = self._state(key, now)
            return max(1, math.ceil(until - now)) if until > now else None

    def begin(self, key: str) -> None:
        """시도 자리를 예약한다. 잠금 중이거나 자리가 없으면 `AttemptRejected`."""
        now = self._clock.now()
        with self._lock:
            failures, until = self._state(key, now)
            if until > now:
                raise AttemptRejected(max(1, math.ceil(until - now)))
            if failures + self._in_flight.get(key, 0) >= self.MAX_FAILURES:
                # 진행 중인 시도가 끝나야 자리가 난다 (보통 1초 안).
                raise AttemptRejected(1)
            self._in_flight[key] = self._in_flight.get(key, 0) + 1

    def finish(self, key: str, failed: bool) -> None:
        now = self._clock.now()
        with self._lock:
            remaining = self._in_flight.get(key, 0) - 1
            if remaining > 0:
                self._in_flight[key] = remaining
            else:
                self._in_flight.pop(key, None)
            if failed:
                self._add_failure(key, now)

    def record_failure(self, key: str) -> None:
        """예약 없이 실패만 기록한다 (테스트·도구용)."""
        with self._lock:
            self._add_failure(key, self._clock.now())


# ── 로그인 실패 제한 (IP별, 연속 실패, 메모리) ──────────────


@dataclass
class _IpAttempts:
    failures: int = 0
    last_failure_at: float = 0.0
    locked_until: float = 0.0


class LoginAttemptLimiter(ReservingLimiter):
    MAX_FAILURES = 5
    LOCK_SECONDS = 15 * 60
    # 마지막 실패 후 이 시간이 지나면 연속 실패 횟수를 잊는다 (몇 주 전 실패가 누적되지 않게).
    FORGET_SECONDS = 15 * 60

    def __init__(self, clock: Clock, max_keys: int = 10_000) -> None:
        super().__init__(clock)
        self.max_keys = max_keys
        self._entries: OrderedDict[str, _IpAttempts] = OrderedDict()

    def _entry(self, key: str, now: float) -> _IpAttempts | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.locked_until and entry.locked_until <= now:
            # 잠금이 풀렸다: 새로 센다.
            entry.failures, entry.locked_until = 0, 0.0
        elif (
            not entry.locked_until
            and entry.failures
            and now - entry.last_failure_at >= self.FORGET_SECONDS
        ):
            entry.failures = 0
        return entry

    def _state(self, key: str, now: float) -> tuple[int, float]:
        entry = self._entry(key, now)
        return (entry.failures, entry.locked_until) if entry else (0, 0.0)

    def _add_failure(self, key: str, now: float) -> None:
        entry = self._entry(key, now)
        if entry is None:
            entry = _IpAttempts()
            self._entries[key] = entry
        self._entries.move_to_end(key)
        entry.failures += 1
        entry.last_failure_at = now
        if entry.failures >= self.MAX_FAILURES and entry.locked_until <= now:
            entry.locked_until = now + self.LOCK_SECONDS
        self._evict(now, keep=key)

    def reset(self, key: str) -> None:
        """성공: 연속 실패 횟수를 초기화한다 (진행 중 예약은 유지)."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.failures, entry.locked_until = 0, 0.0

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _evict(self, now: float, keep: str) -> None:
        if len(self._entries) <= self.max_keys:
            return
        stale = [
            k
            for k, e in self._entries.items()
            if k != keep
            and e.locked_until <= now
            and now - e.last_failure_at >= self.FORGET_SECONDS
        ]
        for k in stale:
            del self._entries[k]
        while len(self._entries) > self.max_keys:
            oldest = next(iter(self._entries))
            if oldest == keep:
                break
            del self._entries[oldest]


# ── 계정 단위 2단계 실패 상한 (모든 IP 합산, 15분 창, DB 저장) ──────


class AccountAttemptLimiter(ReservingLimiter):
    """TOTP·복구 코드 실패를 계정(user id)마다 센다. 키는 `str(user_id)`.

    확정된 실패(`login_code_failures`)와 잠금 끝 시각(`login_code_locks`)은 DB에 두어
    프로세스가 다시 시작돼도 이어진다. 진행 중 시도 수만 메모리에 있다.
    잠금이 끝나면 새로 센다: 마지막 잠금 끝 시각 이전의 실패는 세지 않는다.
    2단계 성공으로 기록을 지우지 않는다 (실패는 창이 지나야 빠진다).
    """

    MAX_FAILURES = 10
    WINDOW_SECONDS = 15 * 60
    LOCK_SECONDS = 15 * 60

    def __init__(self, clock: Clock, connect: Callable[[], sqlite3.Connection]) -> None:
        super().__init__(clock)
        self._connect = connect

    def _count(self, conn: sqlite3.Connection, user_id: int, now: float, until: float) -> int:
        row = conn.execute(
            "SELECT COUNT(*) FROM login_code_failures"
            " WHERE user_id = ? AND failed_at > ? AND failed_at >= ?",
            (user_id, now - self.WINDOW_SECONDS, until),
        ).fetchone()
        return int(row[0])

    @staticmethod
    def _locked_until(conn: sqlite3.Connection, user_id: int) -> float:
        row = conn.execute(
            "SELECT locked_until FROM login_code_locks WHERE user_id = ?", (user_id,)
        ).fetchone()
        return float(row[0]) if row else 0.0

    def _state(self, key: str, now: float) -> tuple[int, float]:
        user_id = int(key)
        conn = self._connect()
        try:
            until = self._locked_until(conn, user_id)
            if until > now:
                return 0, until
            return self._count(conn, user_id, now, until), until
        finally:
            conn.close()

    def _add_failure(self, key: str, now: float) -> None:
        user_id = int(key)
        conn = self._connect()
        try:
            with transaction(conn):
                # 창 밖의 기록은 더 쓰지 않으므로 정리한다.
                conn.execute(
                    "DELETE FROM login_code_failures WHERE user_id = ? AND failed_at <= ?",
                    (user_id, now - self.WINDOW_SECONDS),
                )
                conn.execute(
                    "INSERT INTO login_code_failures (user_id, failed_at) VALUES (?, ?)",
                    (user_id, now),
                )
                until = self._locked_until(conn, user_id)
                if until > now:
                    return
                count = self._count(conn, user_id, now, until)
                if count < self.MAX_FAILURES:
                    return
                conn.execute(
                    "INSERT INTO login_code_locks (user_id, locked_until) VALUES (?, ?)"
                    " ON CONFLICT (user_id) DO UPDATE SET locked_until = excluded.locked_until",
                    (user_id, now + self.LOCK_SECONDS),
                )
        finally:
            conn.close()
        # 값·IP 없이 횟수만 남긴다.
        logger.warning(
            "2단계 인증 실패가 %d분 안에 %d회에 이르러 %d분 동안 로그인 2단계를 막습니다. "
            "비밀번호가 유출되었을 수 있습니다.",
            self.WINDOW_SECONDS // 60,
            count,
            self.LOCK_SECONDS // 60,
        )
