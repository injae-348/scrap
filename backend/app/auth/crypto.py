"""비밀번호·TOTP·토큰·복구 코드 관련 순수 함수.

비밀번호 (Argon2id, argon2-cffi)
- time_cost=2, memory_cost=19 MiB, parallelism=1: OWASP 최소 권장값.
  서버가 1코어·RAM 1GB(api 컨테이너 384MB)라 기본값(64 MiB, parallelism 4)은 과하다.
  1코어에서는 parallelism을 올려도 빨라지지 않고 메모리만 더 쓴다.
- 동시에 해시를 계산하는 스레드 수를 세마포어로 2개로 제한한다 (스레드풀 40개가 한꺼번에
  19 MiB씩 잡아 메모리 상한을 넘는 일을 막는다). 자리를 `HASH_WAIT_SECONDS` 안에 못 얻으면
  `PasswordHasherBusy`를 내고 라우트는 429로 답한다 (스레드풀이 대기로 고갈되지 않게).
- 파라미터를 바꾸면 다음 로그인 성공 때 `needs_rehash`로 새 파라미터 해시로 바꾼다.

토큰 해시
- 세션 토큰: 32바이트 랜덤(쿠키) → DB에는 HMAC-SHA256(SESSION_SECRET에서 파생한 키, 토큰)만.
  DB만 유출되어서는 쿠키를 만들 수 없고, SESSION_SECRET을 바꾸면 모든 세션이 무효가 된다
  (전체 로그아웃 효과).
- 복구 코드: 80비트 랜덤 → DB에는 SHA-256만. SESSION_SECRET에 묶지 않는 이유는 비밀값을
  교체했을 때 복구 코드까지 사라져 잠기는 일을 막기 위함. 80비트라 해시가 유출되어도
  무차별 대입은 현실적으로 불가능하다.
"""

import base64
import hashlib
import hmac
import io
import secrets
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import pyotp
import qrcode
import qrcode.image.svg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# ── 비밀번호 ─────────────────────────────────────────

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 1024

_hasher = PasswordHasher(
    time_cost=2, memory_cost=19 * 1024, parallelism=1, hash_len=32, salt_len=16
)
_hash_slots = threading.BoundedSemaphore(2)
HASH_WAIT_SECONDS = 2.0
_dummy_hash: str | None = None
_dummy_lock = threading.Lock()


class PasswordHasherBusy(Exception):
    """Argon2 계산 자리를 제한 시간 안에 얻지 못했다."""


@contextmanager
def _hash_slot() -> Iterator[None]:
    if not _hash_slots.acquire(timeout=HASH_WAIT_SECONDS):
        raise PasswordHasherBusy
    try:
        yield
    finally:
        _hash_slots.release()


def hash_password(password: str) -> str:
    with _hash_slot():
        return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    with _hash_slot():
        try:
            return _hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def prepare_dummy_hash() -> str:
    """가짜 해시를 한 번만 만든다. 앱 시작 때 불러 첫 요청의 시간 차이를 없앤다."""
    global _dummy_hash
    with _dummy_lock:
        if _dummy_hash is None:
            _dummy_hash = _hasher.hash(secrets.token_hex(16))
        return _dummy_hash


def burn_password_check(password: str) -> None:
    """없는 아이디일 때도 비슷한 시간이 걸리게 가짜 해시를 검증한다 (아이디 존재 여부 숨김)."""
    verify_password(prepare_dummy_hash(), password)


# ── TOTP ────────────────────────────────────────────

TOTP_INTERVAL = 30
TOTP_DIGITS = 6
TOTP_ISSUER = "scrap-app"  # 일반 이름. 실제 도메인을 넣지 않는다.


def new_totp_secret() -> str:
    return pyotp.random_base32()  # 32자 = 160비트


def totp_step(now: float) -> int:
    return int(now // TOTP_INTERVAL)


def match_totp(secret: str, code: str, now: float, last_step: int | None) -> int | None:
    """맞으면 일치한 구간 번호를, 틀리거나 이미 쓴 구간이면 None을 돌려준다.

    현재 구간과 앞뒤 1구간을 허용한다. `last_step` 이하 구간은 재사용으로 보고 거부한다.
    """
    code = "".join(code.split())
    # isascii: str.isdigit()은 '١٢٣' 같은 유니코드 숫자도 참으로 본다.
    if len(code) != TOTP_DIGITS or not (code.isascii() and code.isdigit()):
        return None
    totp = pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVAL)
    current = totp_step(now)
    for step in (current - 1, current, current + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def totp_qr_data_url(secret: str, username: str) -> str:
    """otpauth URI를 담은 QR을 SVG data URL로 만든다 (Pillow 불필요)."""
    uri = pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=TOTP_ISSUER)
    image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    image.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


# ── 토큰 ────────────────────────────────────────────


def new_token() -> str:
    """쿠키·challenge_id용 랜덤 토큰 (256비트, URL-safe)."""
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class TokenHasher:
    """SESSION_SECRET에서 용도별 키를 파생해 HMAC-SHA256으로 토큰을 해시한다."""

    session_key: bytes = field(repr=False)

    @classmethod
    def from_secret(cls, secret: str) -> "TokenHasher":
        root = secret.encode("utf-8")
        return cls(session_key=hmac.new(root, b"scrap-app/session-token/v1", "sha256").digest())

    def session_token_hash(self, token: str) -> str:
        return hmac.new(self.session_key, token.encode("utf-8"), "sha256").hexdigest()


# ── 복구 코드 ────────────────────────────────────────

RECOVERY_CODE_COUNT = 10
# 헷갈리는 글자(0/O, 1/I)를 뺀 32자 → 글자당 5비트, 16자 = 80비트.
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_RECOVERY_LENGTH = 16
_RECOVERY_GROUP = 4


def new_recovery_codes() -> list[str]:
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_LENGTH))
        groups = [raw[i : i + _RECOVERY_GROUP] for i in range(0, _RECOVERY_LENGTH, _RECOVERY_GROUP)]
        codes.append("-".join(groups))
    return codes


def normalize_recovery_code(code: str) -> str:
    """대소문자·하이픈·공백을 무시한다."""
    return "".join(ch for ch in code if ch != "-" and not ch.isspace()).upper()


def recovery_code_hash(code: str) -> str:
    return hashlib.sha256(normalize_recovery_code(code).encode("utf-8")).hexdigest()
