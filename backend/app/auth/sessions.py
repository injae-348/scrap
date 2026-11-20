"""세션 쿠키·세션 테이블과 인증 의존성.

Phase 5 이후 라우터는 `get_current_session`을 의존성으로 쓴다:

    router = APIRouter(prefix="/api", dependencies=[Depends(get_current_session)])
    # 또는 라우트 인자로 session: CurrentSession = Depends(get_current_session)

규칙 (docs/API.md 인증 세부 규칙)
- 쿠키: HttpOnly, Secure, SameSite=Lax, Path=/, Max-Age 400일. 세션이 확인될 때마다 쿠키를 다시 내려
  만료를 갱신한다.
- DB에는 토큰의 HMAC만 저장한다.
- 180일 동안 쓰지 않은 세션은 만료(삭제) → 401.
- `last_seen_at`은 마지막 갱신 후 `LAST_SEEN_UPDATE_SECONDS`(1시간)가 지났을 때만 쓴다
  (요청마다 DB 쓰기 방지).
"""

import sqlite3
from dataclasses import dataclass

from fastapi import Depends, Request, Response

from app.auth.crypto import TokenHasher, new_token
from app.clock import Clock, from_iso, to_iso
from app.config import Settings
from app.db import get_db
from app.errors import ApiError

SESSION_COOKIE_MAX_AGE = 400 * 24 * 60 * 60
SESSION_IDLE_EXPIRY_SECONDS = 180 * 24 * 60 * 60
LAST_SEEN_UPDATE_SECONDS = 60 * 60
USER_AGENT_MAX_LENGTH = 512


@dataclass(frozen=True)
class CurrentSession:
    id: int
    user_id: int


def cookie_name(settings: Settings, base: str) -> str:
    # Secure일 때 `__Host-` 접두사: 브라우저가 Secure + Path=/ + Domain 없음을 강제한다
    # (서브도메인이 같은 이름의 쿠키를 심는 공격 방지).
    return f"__Host-{base}" if settings.cookie_secure else base


def session_cookie_name(settings: Settings) -> str:
    return cookie_name(settings, "session")


def set_cookie(response: Response, settings: Settings, base: str, value: str, max_age: int) -> None:
    response.set_cookie(
        cookie_name(settings, base),
        value,
        max_age=max_age,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_cookie(response: Response, settings: Settings, base: str) -> None:
    response.delete_cookie(
        cookie_name(settings, base),
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    # 같은 응답에서 앞서 갱신한 세션 쿠키(Set-Cookie)가 있으면 지우고 삭제 쿠키만 남긴다.
    name = session_cookie_name(settings)
    kept = [
        (k, v)
        for k, v in response.headers.raw
        if not (k.lower() == b"set-cookie" and v.decode("latin-1").startswith(f"{name}="))
    ]
    response.headers.raw[:] = kept
    clear_cookie(response, settings, "session")


def create_session(
    conn: sqlite3.Connection,
    hasher: TokenHasher,
    clock: Clock,
    user_id: int,
    user_agent: str | None,
) -> str:
    """세션을 만들고 쿠키에 넣을 원본 토큰을 돌려준다. 호출하는 쪽이 트랜잭션을 관리한다."""
    token = new_token()
    now = to_iso(clock.now())
    conn.execute(
        "INSERT INTO sessions (user_id, token_hash, user_agent, created_at, last_seen_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            user_id,
            hasher.session_token_hash(token),
            (user_agent or "")[:USER_AGENT_MAX_LENGTH],
            now,
            now,
        ),
    )
    return token


def set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    set_cookie(response, settings, "session", token, SESSION_COOKIE_MAX_AGE)


def resolve_session(
    request: Request, response: Response, conn: sqlite3.Connection
) -> CurrentSession | None:
    """쿠키의 세션을 확인한다. 유효하면 쿠키·last_seen_at을 갱신하고, 아니면 None."""
    settings: Settings = request.app.state.settings
    hasher: TokenHasher = request.app.state.token_hasher
    clock: Clock = request.app.state.clock

    token = request.cookies.get(session_cookie_name(settings))
    if not token or len(token) > 256:
        return None
    row = conn.execute(
        "SELECT id, user_id, last_seen_at FROM sessions WHERE token_hash = ?",
        (hasher.session_token_hash(token),),
    ).fetchone()
    if row is None:
        return None

    now = clock.now()
    idle = now - from_iso(row["last_seen_at"])
    if idle >= SESSION_IDLE_EXPIRY_SECONDS:
        conn.execute("DELETE FROM sessions WHERE id = ?", (row["id"],))
        return None
    if idle >= LAST_SEEN_UPDATE_SECONDS:
        conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (to_iso(now), row["id"]))

    set_session_cookie(response, settings, token)
    session = CurrentSession(id=row["id"], user_id=row["user_id"])
    request.state.session = session
    return session


def get_current_session(
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),  # noqa: B008
) -> CurrentSession:
    """인증이 필요한 라우트의 의존성. 세션이 없거나 만료되면 401 `unauthorized`."""
    session = resolve_session(request, response, conn)
    if session is None:
        raise ApiError(401, "unauthorized", "로그인이 필요합니다.")
    return session
