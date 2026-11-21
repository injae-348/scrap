"""환경변수 기반 설정.

운영 기본값은 안전한 쪽으로 둔다.
- `SESSION_SECRET`: 필수. 없거나 자리표시자이거나 32자 미만이면 `Settings` 생성 시 `ConfigError`.
- `SETUP_TOKEN`: 선택. 최초 가입(`/auth/setup`)에 필요한 토큰. 없거나 자리표시자·공개 예시값이거나
  32자 미만이거나 글자 종류가 너무 적거나 `SESSION_SECRET`과 같으면 "미설정"(None)으로 보고
  가입을 막는다 (앱은 정상 기동).
- `COOKIE_SECURE`: 기본 켜짐. `0`일 때만 끈다 (로컬 http 개발용).
- 허용 출처(CSRF Origin 검사): `https://<SITE_DOMAIN>` + `ALLOWED_ORIGINS`(쉼표 구분, 개발용).
- 운영 설정 가드: `SITE_DOMAIN`이 있으면(운영) `COOKIE_SECURE=0`, https가 아닌 허용 출처,
  `ENABLE_API_DOCS=1`을 받지 않고 기동을 거부한다.
- `ANTHROPIC_API_KEY`: 선택. 없거나 `.env.example` 자리표시자이거나 `sk-ant-`로 시작하지 않으면
  "미설정"(None) → 앱은 정상 기동하고 `/api/ai/*`만 503 `ai_unavailable`.
- `ANTHROPIC_FALLBACKS`: 기본 켜짐. 정확히 `0`이면 거부 시 다른 모델로 다시 처리하지 않는다.
- `ANTHROPIC_MODEL`(기본 `claude-opus-5-5`), `AI_PER_MINUTE`(기본 10), `AI_PER_DAY`(기본 200):
  형식이 틀리면 기본값을 쓰고 경고 로그를 남긴다 (AI 설정 실수로 앱 전체가 멈추지 않게).

비밀값은 로그·예외 메시지에 넣지 않는다.
"""

import logging
import os
import re
from dataclasses import dataclass, field

logger = logging.getLogger("app")

# 로컬 개발용 기본 경로 (작업 디렉터리 backend/ 기준). 운영에서는 compose가 DB_PATH를 지정한다.
DEFAULT_DB_PATH = "./data/dev.db"

# .env.example 에 들어 있는 자리표시자. 이 값 그대로면 기동을 거부한다.
SESSION_SECRET_PLACEHOLDER = "change-me-generate-with-openssl-rand-hex-32"  # noqa: S105
SESSION_SECRET_MIN_LENGTH = 32
# SETUP_TOKEN 도 같은 자리표시자·최소 길이 규칙을 쓴다.
SETUP_TOKEN_MIN_LENGTH = 32
SETUP_TOKEN_MIN_DISTINCT_CHARS = 10
# 예전에 공개된 예시값. 토큰으로 받지 않는다.
# 테스트는 실행할 때마다 무작위 토큰을 만들어 쓴다 (tests/conftest.py).
PUBLIC_SETUP_TOKEN_VALUES = frozenset(
    {
        SESSION_SECRET_PLACEHOLDER,
        "local-dev-setup-token-not-a-real-secret-0000",
    }
)

# 공통 요청 제한: IP별 분당 요청 수 (/api/* 전체, health 포함).
DEFAULT_REQUESTS_PER_MINUTE = 300

# AI (Phase 7)
ANTHROPIC_API_KEY_PLACEHOLDER = "sk-ant-xxxx"  # .env.example 의 가짜 값
ANTHROPIC_API_KEY_PREFIX = "sk-ant-"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
DEFAULT_AI_PER_MINUTE = 10
DEFAULT_AI_PER_DAY = 200
AI_LIMIT_MAX = 100_000
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")

_TRUE_VALUES = {"1", "true", "yes", "on"}


class ConfigError(RuntimeError):
    """설정이 잘못되어 앱을 시작할 수 없다. 메시지에 비밀값을 넣지 않는다."""


def validate_session_secret(secret: str | None) -> str:
    value = (secret or "").strip()
    if not value:
        raise ConfigError("SESSION_SECRET 환경변수가 없습니다. `openssl rand -hex 32`로 만드세요.")
    if value == SESSION_SECRET_PLACEHOLDER:
        raise ConfigError(
            "SESSION_SECRET 이 .env.example 의 자리표시자 그대로입니다. "
            "`openssl rand -hex 32`로 새 값을 만드세요."
        )
    if len(value) < SESSION_SECRET_MIN_LENGTH:
        raise ConfigError(
            f"SESSION_SECRET 이 너무 짧습니다 ({SESSION_SECRET_MIN_LENGTH}자 이상 필요). "
            "`openssl rand -hex 32`로 만드세요."
        )
    return value


def normalize_setup_token(token: str | None, session_secret: str | None = None) -> str | None:
    """쓸 수 있는 가입 토큰이면 그 값을, 아니면 None(미설정)을 돌려준다.

    미설정: 없음·빈 값, 공개된 값(자리표시자·예전 README 예시), 32자 미만,
    서로 다른 글자가 10개 미만(`aaaa…` 같은 값), `SESSION_SECRET`과 같음.
    """
    value = (token or "").strip()
    if (
        not value
        or value in PUBLIC_SETUP_TOKEN_VALUES
        or len(value) < SETUP_TOKEN_MIN_LENGTH
        or len(set(value)) < SETUP_TOKEN_MIN_DISTINCT_CHARS
    ):
        return None
    if session_secret is not None and value == session_secret.strip():
        logger.warning(
            "SETUP_TOKEN 이 SESSION_SECRET 과 같아 무시합니다 (가입 불가). "
            "`openssl rand -hex 32`로 따로 만드세요."
        )
        return None
    return value


def normalize_anthropic_api_key(key: str | None) -> str | None:
    """쓸 수 있는 키면 그 값을, 아니면 None(미설정 → AI 기능만 503)을 돌려준다.

    값은 로그·예외 메시지에 쓰지 않는다.
    """
    value = (key or "").strip()
    if (
        not value
        or value == ANTHROPIC_API_KEY_PLACEHOLDER
        or not value.startswith(ANTHROPIC_API_KEY_PREFIX)
        or any(ch.isspace() or not ch.isprintable() for ch in value)
    ):
        return None
    return value


def normalize_model(name: str | None) -> str:
    value = (name or "").strip()
    if not value:
        return DEFAULT_ANTHROPIC_MODEL
    if not _MODEL_NAME.match(value):
        logger.warning("ANTHROPIC_MODEL 형식이 올바르지 않아 기본 모델을 씁니다.")
        return DEFAULT_ANTHROPIC_MODEL
    return value


def _positive_int(raw: str | None, name: str, default: int) -> int:
    value = (raw or "").strip()
    if not value:
        return default
    if value.isascii() and value.isdigit() and 1 <= int(value) <= AI_LIMIT_MAX:
        return int(value)
    logger.warning(
        "%s 값이 올바르지 않아 기본값 %d 을(를) 씁니다 (1~%d).", name, default, AI_LIMIT_MAX
    )
    return default


def normalize_origin(value: str) -> str:
    """출처 문자열을 비교용으로 정규화한다 (소문자, 끝 `/` 제거)."""
    return value.strip().rstrip("/").lower()


def _site_origin(site_domain: str) -> str | None:
    domain = site_domain.strip().rstrip("/")
    if not domain:
        return None
    if "://" not in domain:
        domain = f"https://{domain}"
    return normalize_origin(domain)


@dataclass(frozen=True)
class Settings:
    db_path: str
    enable_api_docs: bool
    # repr=False: 디버그 출력·로그에 비밀값이 찍히지 않게 한다.
    session_secret: str = field(repr=False)
    # SITE_DOMAIN 에서 만든 운영 출처(`https://<SITE_DOMAIN>`). 있으면 운영으로 본다.
    site_origin: str | None = None
    # ALLOWED_ORIGINS (개발용 추가 출처)
    extra_origins: frozenset[str] = frozenset()
    cookie_secure: bool = True
    requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE
    # None이면 미설정 → 가입 불가. repr=False: 로그·예외에 값이 찍히지 않게 한다.
    setup_token: str | None = field(default=None, repr=False)
    # None이면 미설정 → /api/ai/* 503. repr=False: 로그·예외에 값이 찍히지 않게 한다.
    anthropic_api_key: str | None = field(default=None, repr=False)
    anthropic_model: str = DEFAULT_ANTHROPIC_MODEL
    ai_per_minute: int = DEFAULT_AI_PER_MINUTE
    ai_per_day: int = DEFAULT_AI_PER_DAY
    # 거부 시 다른 모델로 다시 처리(서버측 fallbacks). 정확히 "0"일 때만 끈다.
    anthropic_fallbacks: bool = True

    def __post_init__(self) -> None:
        # 직접 만든 Settings(테스트 등)도 같은 규칙으로 검사한다.
        object.__setattr__(self, "session_secret", validate_session_secret(self.session_secret))
        object.__setattr__(
            self, "setup_token", normalize_setup_token(self.setup_token, self.session_secret)
        )
        object.__setattr__(
            self, "anthropic_api_key", normalize_anthropic_api_key(self.anthropic_api_key)
        )
        self._check_production_guard()

    @property
    def ai_available(self) -> bool:
        return self.anthropic_api_key is not None

    @property
    def production(self) -> bool:
        return self.site_origin is not None

    @property
    def allowed_origins(self) -> frozenset[str]:
        site = {self.site_origin} if self.site_origin else set()
        return frozenset(site | set(self.extra_origins))

    def _check_production_guard(self) -> None:
        """운영(SITE_DOMAIN 있음)에 개발용 설정이 섞이면 기동을 거부한다.

        메시지에 값(도메인·출처)을 넣지 않는다.
        """
        if not self.production:
            return
        if not self.cookie_secure:
            raise ConfigError(
                "SITE_DOMAIN 이 설정된 운영 환경에서는 COOKIE_SECURE=0 을 쓸 수 없습니다. "
                "서버 .env 에서 COOKIE_SECURE 줄을 지우세요."
            )
        if any(not origin.startswith("https://") for origin in self.allowed_origins):
            raise ConfigError(
                "SITE_DOMAIN 이 설정된 운영 환경에서는 https 가 아닌 허용 출처를 쓸 수 없습니다. "
                "SITE_DOMAIN 형식과 ALLOWED_ORIGINS 를 확인하세요 (운영에서는 비워 둡니다)."
            )
        if self.enable_api_docs:
            raise ConfigError(
                "SITE_DOMAIN 이 설정된 운영 환경에서는 ENABLE_API_DOCS 를 켤 수 없습니다. "
                "서버 .env 에서 ENABLE_API_DOCS 줄을 지우세요."
            )


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


def _load_extra_origins() -> frozenset[str]:
    return frozenset(
        normalize_origin(item)
        for item in os.environ.get("ALLOWED_ORIGINS", "").split(",")
        if item.strip()
    )


def load_settings() -> Settings:
    db_path = os.environ.get("DB_PATH", "").strip() or DEFAULT_DB_PATH
    return Settings(
        db_path=db_path,
        # OpenAPI 문서(/api/docs, /api/redoc, /api/openapi.json)는 기본 비활성화. 로컬에서만 켠다.
        enable_api_docs=_env_bool("ENABLE_API_DOCS"),
        session_secret=os.environ.get("SESSION_SECRET", ""),
        site_origin=_site_origin(os.environ.get("SITE_DOMAIN", "")),
        extra_origins=_load_extra_origins(),
        # 기본 켜짐. 정확히 "0"일 때만 끈다 (로컬 http 개발용).
        cookie_secure=os.environ.get("COOKIE_SECURE", "").strip() != "0",
        setup_token=os.environ.get("SETUP_TOKEN"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        anthropic_model=normalize_model(os.environ.get("ANTHROPIC_MODEL")),
        ai_per_minute=_positive_int(
            os.environ.get("AI_PER_MINUTE"), "AI_PER_MINUTE", DEFAULT_AI_PER_MINUTE
        ),
        ai_per_day=_positive_int(os.environ.get("AI_PER_DAY"), "AI_PER_DAY", DEFAULT_AI_PER_DAY),
        anthropic_fallbacks=os.environ.get("ANTHROPIC_FALLBACKS", "").strip() != "0",
    )
