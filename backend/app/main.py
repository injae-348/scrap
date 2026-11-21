"""FastAPI 진입점: `app.main:app` (작업 디렉터리 backend/).

프록시 헤더(X-Forwarded-*) 처리는 uvicorn 실행 옵션(--proxy-headers,
--forwarded-allow-ips)이 담당하므로 앱 코드에서 다루지 않는다.

`app` 객체는 처음 참조될 때 만든다 (모듈 `__getattr__`). uvicorn이 `app.main:app`을 불러오는 순간
`create_app()`이 실행되고, 설정이 잘못되었으면(`SESSION_SECRET` 등) `ConfigError`로 기동이 멈춘다.
테스트는 모듈을 import만 하고 `create_app()`을 직접 부른다.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from app.ai.claude import ClaudeGateway
from app.ai.limits import AiRequestLimiter
from app.ai.router import router as ai_router
from app.auth.crypto import PasswordHasherBusy, TokenHasher, prepare_dummy_hash
from app.auth.router import (
    CHALLENGE_MAX_PENDING,
    CHALLENGE_TTL_SECONDS,
    SETUP_MAX_PENDING,
    SETUP_TTL_SECONDS,
    TOTP_RESET_MAX_PENDING,
    TOTP_RESET_TTL_SECONDS,
)
from app.auth.router import public_router as auth_public_router
from app.auth.router import router as auth_router
from app.clock import Clock
from app.config import Settings, load_settings
from app.csrf import OriginCheckMiddleware
from app.db import Database, DatabaseUnavailableError, check_database
from app.errors import ApiError, error_response, register_error_handlers
from app.guard import RequestGuardMiddleware
from app.headers import NoStoreMiddleware
from app.logfilters import install_log_filters
from app.memstore import TTLStore
from app.meta import PREVIEW_REQUESTS_PER_MINUTE
from app.meta import router as meta_router
from app.pagetext import PageTextFetcher
from app.preview import PreviewFetcher
from app.ratelimit import (
    AccountAttemptLimiter,
    LoginAttemptLimiter,
    RateLimitMiddleware,
    RequestRateLimiter,
)
from app.routing import assert_default_deny, build_protected_router
from app.scraps import router as scraps_router
from app.sources import router as sources_router
from app.topics import router as topics_router

logger = logging.getLogger("app")

# 인증 불필요 라우터. 여기에는 health 만 둔다 (공개 목록: app/routing.py PUBLIC_ENDPOINTS).
public_router = APIRouter(prefix="/api")

# 세션 필수 라우터 목록. 새 기능 라우터는 여기에 추가한다 (상위 라우터가 인증을 건다).
PROTECTED_ROUTERS = (
    auth_router,
    scraps_router,
    sources_router,
    topics_router,
    meta_router,
    ai_router,
)


@public_router.get("/health")
def health(request: Request) -> dict[str, str]:
    """배포 후 헬스체크용. 인증 불필요. DB 연결 + 마이그레이션 적용까지 확인한다.

    동기 함수로 두어 SQLite 파일 I/O가 스레드풀에서 실행되게 한다.
    """
    settings: Settings = request.app.state.settings
    database: Database = request.app.state.db
    try:
        check_database(settings.db_path)
        database.ensure_migrated()
    except DatabaseUnavailableError as exc:
        # 경로·권한 등 상세 원인은 서버 로그에만 남기고 응답에는 넣지 않는다.
        logger.error("헬스체크 실패: %s", exc)
        raise ApiError(503, "db_unavailable", "데이터베이스에 연결할 수 없습니다.") from exc
    return {"status": "ok"}


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 시작 시 마이그레이션을 적용한다. 실패해도 프로세스는 띄워 두고(원인은 로그),
    # /api/health 가 503을 돌려 배포가 실패·롤백되게 한다. 첫 DB 연결 때 다시 시도한다.
    try:
        app.state.db.ensure_migrated()
        _log_setup_token_state(app)
    except DatabaseUnavailableError as exc:
        logger.error("시작 시 마이그레이션 실패: %s", exc)
    # 없는 아이디용 가짜 해시를 미리 만든다 (첫 요청만 해시를 두 번 하는 시간 차이 제거).
    prepare_dummy_hash()
    yield


async def _handle_hasher_busy(_: Request, __: Exception) -> JSONResponse:
    # 비밀번호 해시 자리를 제한 시간 안에 못 얻음: 잠시 뒤 다시 시도하게 한다
    # (실패 횟수에 넣지 않음).
    return error_response(
        429,
        "too_many_requests",
        "요청이 몰려 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        headers={"Retry-After": "1"},
    )


def _log_setup_token_state(app: FastAPI) -> None:
    """가입 토큰 상태 안내. 토큰 값은 절대 로그에 쓰지 않는다."""
    settings: Settings = app.state.settings
    conn = app.state.db.connect()
    try:
        has_user = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
    finally:
        conn.close()
    if has_user and settings.setup_token is not None:
        logger.warning(
            "가입이 이미 완료되었습니다. 서버 .env 의 SETUP_TOKEN 을 지워도 됩니다 "
            "(가입 API는 계속 403)."
        )
    elif not has_user and settings.setup_token is None:
        logger.warning(
            "가입 전인데 SETUP_TOKEN 이 설정되지 않았습니다 (없음·자리표시자·32자 미만). "
            "가입하려면 서버 .env 에 SETUP_TOKEN 을 넣고 다시 시작하세요."
        )


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    # 접근 로그에서 쿼리 문자열(검색어·커서)을 뺀다. 기동 방식과 상관없이 앱을 만들 때 건다.
    install_log_filters()
    settings = settings or load_settings()
    clock = clock or Clock()
    docs = settings.enable_api_docs
    app = FastAPI(
        title="scrap-app API",
        # 운영에서는 OpenAPI 문서를 노출하지 않는다. ENABLE_API_DOCS=1 일 때만 /api 아래에 연다.
        docs_url="/api/docs" if docs else None,
        redoc_url="/api/redoc" if docs else None,
        openapi_url="/api/openapi.json" if docs else None,
        lifespan=_lifespan,
    )
    if not settings.allowed_origins:
        logger.warning(
            "허용 출처가 없습니다 (SITE_DOMAIN, ALLOWED_ORIGINS 미설정). "
            "브라우저의 상태 변경 요청이 403(origin_mismatch)이 됩니다."
        )

    app.state.settings = settings
    app.state.clock = clock
    app.state.db = Database(settings.db_path, clock.now)
    app.state.token_hasher = TokenHasher.from_secret(settings.session_secret)
    app.state.setup_pending = TTLStore(clock, SETUP_TTL_SECONDS, SETUP_MAX_PENDING)
    app.state.login_challenges = TTLStore(clock, CHALLENGE_TTL_SECONDS, CHALLENGE_MAX_PENDING)
    app.state.totp_reset_pending = TTLStore(clock, TOTP_RESET_TTL_SECONDS, TOTP_RESET_MAX_PENDING)
    app.state.login_limiter = LoginAttemptLimiter(clock)
    app.state.account_limiter = AccountAttemptLimiter(clock, app.state.db.connect)
    app.state.request_limiter = RequestRateLimiter(clock, settings.requests_per_minute)
    app.state.preview_fetcher = PreviewFetcher()
    # 서버가 사용자 URL을 가져오는 요청의 IP별 분당 상한
    # (/meta/preview 와 /ai/extract 의 가져오기 합산).
    app.state.fetch_limiter = RequestRateLimiter(clock, PREVIEW_REQUESTS_PER_MINUTE)
    app.state.preview_limiter = app.state.fetch_limiter  # 예전 이름
    app.state.page_fetcher = PageTextFetcher()
    # 키가 없거나 형식이 틀리면 AI 기능만 503 (앱은 정상 기동). 클라이언트는 처음 쓸 때 만든다.
    app.state.ai_gateway = ClaudeGateway(
        settings.anthropic_api_key,
        settings.anthropic_model,
        fallbacks=settings.anthropic_fallbacks,
    )
    app.state.ai_limiter = AiRequestLimiter(
        clock,
        app.state.db.connect,
        settings.ai_per_minute,
        settings.ai_per_day,
        tokens_per_day=settings.ai_tokens_per_day,
    )
    if not settings.ai_available:
        logger.warning(
            "ANTHROPIC_API_KEY 가 설정되지 않았습니다 (없음·자리표시자·형식 오류). "
            "AI 기능(/api/ai/*)은 503 으로 응답합니다."
        )

    register_error_handlers(app)
    app.add_exception_handler(PasswordHasherBusy, _handle_hasher_busy)
    # 나중에 추가한 미들웨어가 바깥쪽:
    # no-store 헤더 → 요청 제한 → 출처 확인 → 본문 상한·세션 사전 확인 → 라우터 순서.
    app.add_middleware(RequestGuardMiddleware, api=app)
    app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.allowed_origins)
    app.add_middleware(
        RateLimitMiddleware,
        limiter=app.state.request_limiter,
        warn_private_clients=settings.production,
    )
    app.add_middleware(NoStoreMiddleware)
    # 인증 기본 거부: 공개 6개만 공개 라우터에, 나머지 /api/* 는 세션 필수 상위 라우터 아래에.
    app.include_router(public_router)
    app.include_router(auth_public_router)
    app.include_router(build_protected_router(PROTECTED_ROUTERS))
    assert_default_deny(app)
    return app


_app: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    # uvicorn `app.main:app` 용 지연 생성 (PEP 562).
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
