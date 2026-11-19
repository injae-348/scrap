"""FastAPI 진입점: `app.main:app` (작업 디렉터리 backend/).

Phase 3: 파이프라인 검증용 빈 앱. `GET /api/health`만 있다.
프록시 헤더(X-Forwarded-*) 처리는 uvicorn 실행 옵션(--proxy-headers,
--forwarded-allow-ips)이 담당하므로 앱 코드에서 다루지 않는다.
"""

import logging

from fastapi import APIRouter, FastAPI, Request

from app.config import Settings, load_settings
from app.db import DatabaseUnavailableError, check_database
from app.errors import ApiError, register_error_handlers

logger = logging.getLogger("app")

router = APIRouter(prefix="/api")


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    """배포 후 헬스체크용. 인증 불필요. DB 연결까지 확인한다.

    동기 함수로 두어 SQLite 파일 I/O가 스레드풀에서 실행되게 한다.
    """
    settings: Settings = request.app.state.settings
    try:
        check_database(settings.db_path)
    except DatabaseUnavailableError as exc:
        # 경로·권한 등 상세 원인은 서버 로그에만 남기고 응답에는 넣지 않는다.
        logger.error("헬스체크 실패: %s", exc)
        raise ApiError(503, "db_unavailable", "데이터베이스에 연결할 수 없습니다.") from exc
    return {"status": "ok"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    docs = settings.enable_api_docs
    app = FastAPI(
        title="scrap-app API",
        # 운영에서는 OpenAPI 문서를 노출하지 않는다. ENABLE_API_DOCS=1 일 때만 /api 아래에 연다.
        docs_url="/api/docs" if docs else None,
        redoc_url="/api/redoc" if docs else None,
        openapi_url="/api/openapi.json" if docs else None,
    )
    app.state.settings = settings
    register_error_handlers(app)
    app.include_router(router)
    return app


app = create_app()
