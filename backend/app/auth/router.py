"""인증 API `/api/auth` (docs/API.md "인증"과 "인증 세부 규칙 (v1.1)").

임시 상태는 서버 메모리(`app.memstore.TTLStore`, 워커 1개)에 둔다:
- 가입 대기(10분, 최대 8개, 틀린 코드 5번이면 폐기): 브라우저별 HttpOnly 쿠키 `setup`으로 묶는다.
- 로그인 challenge(5분, 최대 64개, 1회용, 틀린 코드 5번이면 폐기).
- TOTP 재설정 대기(10분, 최대 8개): 세션 id로 묶는다.
DB에 두지 않는 이유: 몇 분짜리 1회성 상태라 재시작 시 사라져도 처음부터 다시 하면 되고,
미완료 가입 정보(비밀번호 해시·TOTP 비밀값)가 디스크·백업에 남지 않는다.

시도 제한(app/ratelimit.py)은 "예약" 방식이다: 검증을 시작하기 전에 잠금 아래에서 자리를 잡고,
끝날 때 실패를 기록한다. challenge·가입 대기의 틀린 코드 횟수도 검증 전에 미리 올렸다가
성공하면 되돌린다. 그래서 동시에 보낸 요청도 상한을 넘겨 평가되지 않는다.
"""

import hmac
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.auth.crypto import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    burn_password_check,
    hash_password,
    match_totp,
    new_recovery_codes,
    new_token,
    new_totp_secret,
    password_needs_rehash,
    recovery_code_hash,
    totp_qr_data_url,
    verify_password,
)
from app.auth.sessions import (
    CurrentSession,
    clear_cookie,
    clear_session_cookie,
    cookie_name,
    create_session,
    get_current_session,
    resolve_session,
    set_cookie,
    set_session_cookie,
)
from app.clock import to_iso
from app.db import get_db, transaction
from app.errors import ApiError
from app.ratelimit import AttemptRejected, AttemptSlot, ReservingLimiter, client_key

# 인증 불필요 엔드포인트 (app/routing.py PUBLIC_ENDPOINTS). 앱에 직접 붙인다.
public_router = APIRouter(prefix="/api/auth")
# 세션 필수 엔드포인트. app/routing.py 의 세션 필수 상위 라우터(/api) 아래에 붙는다.
router = APIRouter(prefix="/auth")

SETUP_TTL_SECONDS = 10 * 60
SETUP_MAX_PENDING = 8
CHALLENGE_TTL_SECONDS = 5 * 60
CHALLENGE_MAX_PENDING = 64
CHALLENGE_MAX_WRONG_CODES = 5
SETUP_MAX_WRONG_CODES = 5
SQLITE_MAX_INTEGER = 2**63 - 1
TOTP_RESET_TTL_SECONDS = 10 * 60
TOTP_RESET_MAX_PENDING = 8
USERNAME_MAX_LENGTH = 64

SETUP_COOKIE = "setup"

# challenge·가입 대기의 틀린 코드 횟수를 바꿀 때 쓰는 잠금.
_pending_lock = threading.Lock()


# ── 메모리 상태 ──────────────────────────────────────


@dataclass
class PendingSetup:
    username: str
    # repr=False: 디버그 로그·트레이스백에 비밀값이 실리지 않게 한다.
    password_hash: str = field(repr=False)
    totp_secret: str = field(repr=False)
    wrong_codes: int = 0


@dataclass
class LoginChallenge:
    user_id: int
    wrong_codes: int = 0
    used: bool = False


@dataclass(frozen=True)
class PendingTotpReset:
    user_id: int
    totp_secret: str = field(repr=False)


# ── 요청 본문 ────────────────────────────────────────


class Credentials(BaseModel):
    username: str = Field(max_length=256)
    password: str = Field(max_length=PASSWORD_MAX_LENGTH)


class SetupBody(BaseModel):
    # 모두 선택(기본 빈 값): 본문 스키마 검증(400)이 토큰 검사보다 먼저 일어나지 않게 하고,
    # 검사 순서(setup_disabled → 토큰 미설정 → 토큰 불일치 → 입력값)를 라우트 안에서 지킨다.
    # 길이 상한도 라우트에서 검사한다 (_validate_username, _validate_password).
    username: str = ""
    password: str = ""
    setup_token: str = ""


class CodeBody(BaseModel):
    code: str = Field(max_length=32)


class LoginVerifyBody(BaseModel):
    challenge_id: str = Field(max_length=128)
    code: str | None = Field(default=None, max_length=32)
    recovery_code: str | None = Field(default=None, max_length=64)


class TotpResetBody(BaseModel):
    password: str = Field(max_length=PASSWORD_MAX_LENGTH)
    code: str = Field(max_length=32)


# ── 공통 도우미 ──────────────────────────────────────


def _client_ip(request: Request) -> str:
    # uvicorn --proxy-headers 가 신뢰하는 프록시(web)의 X-Forwarded-For 를 이미 반영한 값.
    # IPv6는 /64 단위 키로 바꾼다.
    return client_key(request.client.host if request.client else None)


def _too_many_attempts(retry_after: int) -> ApiError:
    return ApiError(
        429,
        "too_many_attempts",
        "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.",
        headers={"Retry-After": str(retry_after)},
    )


@contextmanager
def _reserve(limiter: ReservingLimiter, key: str) -> Iterator[AttemptSlot]:
    """시도 자리를 예약한다. 잠금 중이거나 자리가 없으면 429 `too_many_attempts`.

    블록 안에서 `slot.fail()`을 부르면 끝날 때 실패 1회로 기록된다.
    """
    try:
        limiter.begin(key)
    except AttemptRejected as exc:
        raise _too_many_attempts(exc.retry_after) from None
    slot = AttemptSlot()
    try:
        yield slot
    finally:
        limiter.finish(key, slot.failed)


def _ip_attempt(request: Request) -> AbstractContextManager[AttemptSlot]:
    """IP별 로그인 실패 제한 자리 예약."""
    return _reserve(request.app.state.login_limiter, _client_ip(request))


def _account_attempt(request: Request, user_id: int) -> AbstractContextManager[AttemptSlot]:
    """계정 단위(모든 IP 합산) 2단계 실패 상한 자리 예약."""
    return _reserve(request.app.state.account_limiter, str(user_id))


def _reset_failures(request: Request) -> None:
    request.app.state.login_limiter.reset(_client_ip(request))


def _now(request: Request) -> float:
    return request.app.state.clock.now()


def _user_exists(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def _setup_disabled() -> ApiError:
    return ApiError(403, "setup_disabled", "이미 가입이 완료되었습니다. 로그인해 주세요.")


def _invalid_code() -> ApiError:
    return ApiError(401, "invalid_code", "인증 코드가 올바르지 않습니다.")


def _validate_username(raw: str) -> str:
    username = raw.strip()
    if not username or len(username) > USERNAME_MAX_LENGTH:
        raise ApiError(400, "invalid_input", f"아이디는 1~{USERNAME_MAX_LENGTH}자로 입력해 주세요.")
    if any(not ch.isprintable() for ch in username):
        raise ApiError(400, "invalid_input", "아이디에 사용할 수 없는 문자가 있습니다.")
    return username


def _validate_password(password: str) -> None:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ApiError(
            400, "invalid_input", f"비밀번호는 {PASSWORD_MIN_LENGTH}자 이상이어야 합니다."
        )
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ApiError(400, "invalid_input", f"비밀번호는 {PASSWORD_MAX_LENGTH}자 이하여야 합니다.")


def _check_setup_token(request: Request, given: str) -> None:
    """가입 토큰 검사 (docs/API.md 가입 토큰 v1.2). Argon2 해시 계산 전에 부른다."""
    expected: str | None = request.app.state.settings.setup_token
    if expected is None:
        raise ApiError(
            403,
            "setup_token_not_configured",
            "서버에 가입 토큰(SETUP_TOKEN)이 설정되지 않아 가입할 수 없습니다.",
        )
    # 틀린 토큰은 로그인 실패 제한에 함께 센다 → 잠금 중이면 맞는 토큰도 429.
    with _ip_attempt(request) as slot:
        if not hmac.compare_digest(given.strip().encode("utf-8"), expected.encode("utf-8")):
            slot.fail()
            raise ApiError(403, "invalid_setup_token", "가입 토큰이 올바르지 않습니다.")


def _consume_totp(conn: sqlite3.Connection, user: sqlite3.Row, code: str, now: float) -> bool:
    """TOTP를 확인하고, 맞으면 사용한 구간을 기록한다 (같은 구간 재사용 거부).

    조건부 UPDATE로 기록하므로 같은 코드를 동시에 두 번 보내도 한 번만 성공한다.
    """
    step = match_totp(user["totp_secret"], code, now, user["totp_last_step"])
    if step is None:
        return False
    cur = conn.execute(
        "UPDATE users SET totp_last_step = ?"
        " WHERE id = ? AND (totp_last_step IS NULL OR totp_last_step < ?)",
        (step, user["id"], step),
    )
    return cur.rowcount == 1


def _consume_recovery_code(conn: sqlite3.Connection, user_id: int, code: str, now: float) -> bool:
    cur = conn.execute(
        "UPDATE recovery_codes SET used_at = ?"
        " WHERE id = (SELECT id FROM recovery_codes"
        "             WHERE user_id = ? AND code_hash = ? AND used_at IS NULL LIMIT 1)",
        (to_iso(now), user_id, recovery_code_hash(code)),
    )
    return cur.rowcount == 1


def _insert_recovery_codes(conn: sqlite3.Connection, user_id: int, codes: list[str]) -> None:
    conn.executemany(
        "INSERT INTO recovery_codes (user_id, code_hash) VALUES (?, ?)",
        [(user_id, recovery_code_hash(code)) for code in codes],
    )


def _load_user(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, username, password_hash, totp_secret, totp_last_step FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()


# ── 상태 ────────────────────────────────────────────


@public_router.get("/status")
def status(
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),  # noqa: B008
) -> dict[str, bool]:
    return {
        "setup_required": not _user_exists(conn),
        "logged_in": resolve_session(request, response, conn) is not None,
    }


# ── 최초 가입 ────────────────────────────────────────


@public_router.post("/setup")
def setup(
    body: SetupBody,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),  # noqa: B008
) -> dict[str, str]:
    if _user_exists(conn):
        raise _setup_disabled()
    _check_setup_token(request, body.setup_token)
    username = _validate_username(body.username)
    _validate_password(body.password)

    settings = request.app.state.settings
    store = request.app.state.setup_pending
    secret = new_totp_secret()
    pending = PendingSetup(
        username=username, password_hash=hash_password(body.password), totp_secret=secret
    )

    # 같은 브라우저가 다시 시작하면 이전 대기 정보를 버리고 새로 만든다.
    old_token = request.cookies.get(cookie_name(settings, SETUP_COOKIE))
    if old_token:
        store.pop(old_token)
    token = new_token()
    store.put(token, pending)
    set_cookie(response, settings, SETUP_COOKIE, token, SETUP_TTL_SECONDS)
    return {"qr_data_url": totp_qr_data_url(secret, username), "secret": secret}


@public_router.post("/setup/verify")
def setup_verify(
    body: CodeBody,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),  # noqa: B008
) -> dict[str, list[str]]:
    if _user_exists(conn):
        raise _setup_disabled()

    settings = request.app.state.settings
    store = request.app.state.setup_pending
    token = request.cookies.get(cookie_name(settings, SETUP_COOKIE))
    pending: PendingSetup | None = store.get(token) if token else None
    if pending is None:
        raise ApiError(400, "setup_expired", "가입 시간이 지났습니다. 처음부터 다시 진행해 주세요.")

    # 틀린 코드 횟수를 먼저 올려 자리를 잡는다 (동시 요청도 5번까지만 평가).
    with _pending_lock:
        if pending.wrong_codes >= SETUP_MAX_WRONG_CODES:
            raise ApiError(
                400, "setup_expired", "가입 시간이 지났습니다. 처음부터 다시 진행해 주세요."
            )
        pending.wrong_codes += 1

    now = _now(request)
    step = match_totp(pending.totp_secret, body.code, now, None)
    if step is None:
        with _pending_lock:
            if pending.wrong_codes >= SETUP_MAX_WRONG_CODES:
                store.pop(token or "")
        raise _invalid_code()
    with _pending_lock:
        pending.wrong_codes -= 1

    codes = new_recovery_codes()
    with transaction(conn):
        # 두 브라우저가 동시에 확정하는 경우를 막는다 (쓰기 잠금을 잡은 뒤 다시 확인).
        if _user_exists(conn):
            raise _setup_disabled()
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, totp_secret, totp_last_step, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (pending.username, pending.password_hash, pending.totp_secret, step, to_iso(now)),
        )
        user_id = int(cur.lastrowid or 0)
        _insert_recovery_codes(conn, user_id, codes)
        session_token = create_session(
            conn,
            request.app.state.token_hasher,
            request.app.state.clock,
            user_id,
            request.headers.get("user-agent"),
        )

    # 가입이 확정되었으니 다른 대기 정보도 모두 버린다.
    store.clear()
    clear_cookie(response, settings, SETUP_COOKIE)
    set_session_cookie(response, settings, session_token)
    return {"recovery_codes": codes}


# ── 로그인 ──────────────────────────────────────────


def _invalid_credentials() -> ApiError:
    return ApiError(401, "invalid_credentials", "아이디 또는 비밀번호가 올바르지 않습니다.")


@public_router.post("/login")
def login(
    body: Credentials,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),  # noqa: B008
) -> dict[str, object]:
    with _ip_attempt(request) as slot:
        user = conn.execute(
            "SELECT id, password_hash FROM users WHERE username = ?", (body.username.strip(),)
        ).fetchone()
        if user is None:
            burn_password_check(body.password)
            slot.fail()
            raise _invalid_credentials()
        if not verify_password(user["password_hash"], body.password):
            slot.fail()
            raise _invalid_credentials()

    if password_needs_rehash(user["password_hash"]):
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(body.password), user["id"]),
        )

    # 실패 횟수는 여기서 초기화하지 않는다: 비밀번호만 아는 사람이 TOTP를 계속 추측하지 못하게,
    # 2단계까지 모두 성공했을 때만 초기화한다.
    challenge_id = new_token()
    request.app.state.login_challenges.put(challenge_id, LoginChallenge(user_id=user["id"]))
    return {"totp_required": True, "challenge_id": challenge_id}


def _challenge_expired() -> ApiError:
    return ApiError(
        400, "challenge_expired", "로그인 시간이 지났습니다. 처음부터 다시 로그인해 주세요."
    )


def _verify_challenge(
    request: Request, conn: sqlite3.Connection, body: "LoginVerifyBody", ip_slot: AttemptSlot
) -> sqlite3.Row:
    """challenge의 2단계 코드를 확인한다. 성공하면 사용자 행, 실패하면 ApiError.

    순서: challenge 조회 → 계정 단위 자리 예약 → challenge 틀린 횟수 예약 → 검증.
    """
    store = request.app.state.login_challenges
    challenge: LoginChallenge | None = store.get(body.challenge_id)
    if challenge is None or challenge.used:
        raise _challenge_expired()
    user = _load_user(conn, challenge.user_id)
    if user is None:
        store.pop(body.challenge_id)
        raise _challenge_expired()

    with _account_attempt(request, user["id"]) as account_slot:
        with _pending_lock:
            if challenge.used or challenge.wrong_codes >= CHALLENGE_MAX_WRONG_CODES:
                raise _challenge_expired()
            challenge.wrong_codes += 1

        now = _now(request)
        if body.code is not None:
            ok = _consume_totp(conn, user, body.code, now)
        else:
            ok = _consume_recovery_code(conn, user["id"], body.recovery_code or "", now)

        with _pending_lock:
            if not ok:
                if challenge.wrong_codes >= CHALLENGE_MAX_WRONG_CODES:
                    store.pop(body.challenge_id)
            else:
                challenge.wrong_codes -= 1
                # 1회용: 같은 challenge로 동시에 두 번 성공하지 않게 한다.
                if challenge.used:
                    raise _challenge_expired()
                challenge.used = True
                store.pop(body.challenge_id)
        if not ok:
            account_slot.fail()
            ip_slot.fail()
            raise _invalid_code()
    return user


@public_router.post("/login/verify", status_code=204)
def login_verify(
    body: LoginVerifyBody,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),  # noqa: B008
) -> None:
    with _ip_attempt(request) as ip_slot:
        if (body.code is None) == (body.recovery_code is None):
            raise ApiError(
                400, "invalid_input", "인증 코드 또는 복구 코드 중 하나를 입력해 주세요."
            )
        user = _verify_challenge(request, conn, body, ip_slot)

    token = create_session(
        conn,
        request.app.state.token_hasher,
        request.app.state.clock,
        user["id"],
        request.headers.get("user-agent"),
    )
    _reset_failures(request)
    set_session_cookie(response, request.app.state.settings, token)


# ── 로그아웃·기기 목록 ────────────────────────────────


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    session: CurrentSession = Depends(get_current_session),  # noqa: B008
    conn: sqlite3.Connection = Depends(get_db),  # noqa: B008
) -> None:
    conn.execute("DELETE FROM sessions WHERE id = ?", (session.id,))
    request.app.state.totp_reset_pending.pop(str(session.id))
    clear_session_cookie(response, request.app.state.settings)


@router.post("/logout-all", status_code=204)
def logout_all(
    request: Request,
    response: Response,
    session: CurrentSession = Depends(get_current_session),  # noqa: B008
    conn: sqlite3.Connection = Depends(get_db),  # noqa: B008
) -> None:
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (session.user_id,))
    # 세션 id는 재사용되지 않으므로(AUTOINCREMENT) 남은 대기 정보는 아무도 쓸 수 없지만 바로 비운다.
    request.app.state.totp_reset_pending.clear()
    clear_session_cookie(response, request.app.state.settings)


@router.get("/sessions")
def list_sessions(
    session: CurrentSession = Depends(get_current_session),  # noqa: B008
    conn: sqlite3.Connection = Depends(get_db),  # noqa: B008
) -> list[dict[str, object]]:
    rows = conn.execute(
        "SELECT id, user_agent, created_at, last_seen_at FROM sessions"
        " WHERE user_id = ? ORDER BY last_seen_at DESC, id DESC",
        (session.user_id,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "user_agent": row["user_agent"],
            "created_at": row["created_at"],
            "last_seen_at": row["last_seen_at"],
            "current": row["id"] == session.id,
        }
        for row in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: int,
    request: Request,
    response: Response,
    session: CurrentSession = Depends(get_current_session),  # noqa: B008
    conn: sqlite3.Connection = Depends(get_db),  # noqa: B008
) -> None:
    not_found = ApiError(404, "not_found", "로그인된 기기를 찾을 수 없습니다.")
    # SQLite 정수 범위를 넘는 값은 바인딩 때 OverflowError(500)가 나므로 먼저 걸러 404로 답한다.
    if not 1 <= session_id <= SQLITE_MAX_INTEGER:
        raise not_found
    cur = conn.execute(
        "DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, session.user_id)
    )
    if cur.rowcount == 0:
        raise not_found
    request.app.state.totp_reset_pending.pop(str(session_id))
    if session_id == session.id:
        clear_session_cookie(response, request.app.state.settings)


# ── 2차 인증 재설정 ──────────────────────────────────


@router.post("/totp/reset")
def totp_reset(
    body: TotpResetBody,
    request: Request,
    session: CurrentSession = Depends(get_current_session),  # noqa: B008
    conn: sqlite3.Connection = Depends(get_db),  # noqa: B008
) -> dict[str, str]:
    with _ip_attempt(request) as slot:
        user = _load_user(conn, session.user_id)
        if user is None:
            raise ApiError(401, "unauthorized", "로그인이 필요합니다.")
        if not verify_password(user["password_hash"], body.password):
            slot.fail()
            raise ApiError(401, "invalid_credentials", "비밀번호가 올바르지 않습니다.")
        if not _consume_totp(conn, user, body.code, _now(request)):
            slot.fail()
            raise _invalid_code()
    _reset_failures(request)

    secret = new_totp_secret()
    request.app.state.totp_reset_pending.put(
        str(session.id), PendingTotpReset(user_id=user["id"], totp_secret=secret)
    )
    return {"qr_data_url": totp_qr_data_url(secret, user["username"]), "secret": secret}


@router.post("/totp/reset/verify")
def totp_reset_verify(
    body: CodeBody,
    request: Request,
    session: CurrentSession = Depends(get_current_session),  # noqa: B008
    conn: sqlite3.Connection = Depends(get_db),  # noqa: B008
) -> dict[str, list[str]]:
    store = request.app.state.totp_reset_pending
    pending: PendingTotpReset | None = store.get(str(session.id))
    if pending is None or pending.user_id != session.user_id:
        raise ApiError(
            400,
            "totp_reset_expired",
            "2차 인증 재설정 시간이 지났습니다. 처음부터 다시 진행해 주세요.",
        )

    step = match_totp(pending.totp_secret, body.code, _now(request), None)
    if step is None:
        raise _invalid_code()

    codes = new_recovery_codes()
    with transaction(conn):
        conn.execute(
            "UPDATE users SET totp_secret = ?, totp_last_step = ? WHERE id = ?",
            (pending.totp_secret, step, session.user_id),
        )
        conn.execute("DELETE FROM recovery_codes WHERE user_id = ?", (session.user_id,))
        _insert_recovery_codes(conn, session.user_id, codes)
        # 휴대폰 분실 대비: 현재 기기를 뺀 다른 세션은 모두 로그아웃한다.
        conn.execute(
            "DELETE FROM sessions WHERE user_id = ? AND id != ?", (session.user_id, session.id)
        )
    # 남은 재설정 대기 정보는 지운 세션 것뿐이다.
    store.clear()
    return {"recovery_codes": codes}
