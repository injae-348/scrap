"""라우터 구성: 인증 기본 거부 (docs/API.md v1.3 "공통").

- 인증이 필요 없는 엔드포인트는 `PUBLIC_ENDPOINTS` 6개뿐이며, 이것들만 `public_router`에 둔다.
- 나머지 `/api/*` 라우터는 모두 `build_protected_router()`가 만든 상위 라우터 안에 넣는다.
  상위 라우터가 `Depends(get_current_session)`을 걸기 때문에, 새 라우트에 인증을 따로 붙이지 않아도
  세션이 없으면 401 `unauthorized`가 된다.
- 앱을 만들 때 `assert_default_deny(app)`가 등록된 모든 `/api/*` 라우트를 검사한다. 공개 목록 밖의
  라우트에 세션 의존성이 없거나, 공개 목록이 실제 공개 라우트와 다르면 앱이 시작되지 않는다
  (`app.get(...)`으로 앱에 직접 붙인 라우트처럼 상위 라우터를 거치지 않은 경우까지 잡는다).

새 기능 라우터를 추가할 때: 모듈에 `router = APIRouter(prefix="/<이름>")`을 만들고
`build_protected_router()`에 `include_router` 한 줄을 추가한다. 공개 엔드포인트를 늘리는 일은
API.md 변경이 먼저다.
"""

from collections.abc import Callable, Iterable
from typing import Any

from fastapi import APIRouter, Depends, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts

from app.auth.sessions import get_current_session

# (메서드, 경로). docs/API.md "인증 세부 규칙"의 인증 불필요 경로.
PUBLIC_ENDPOINTS: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/health"),
        ("GET", "/api/auth/status"),
        ("POST", "/api/auth/setup"),
        ("POST", "/api/auth/setup/verify"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/login/verify"),
    }
)


def build_protected_router(routers: Iterable[APIRouter]) -> APIRouter:
    """세션 필수 상위 라우터 (`/api`). 넘겨받은 라우터를 모두 이 아래에 둔다."""
    protected = APIRouter(prefix="/api", dependencies=[Depends(get_current_session)])
    for router in routers:
        protected.include_router(router)
    return protected


def _calls(dependant: Dependant) -> Iterable[Callable[..., Any] | None]:
    for sub in dependant.dependencies:
        yield sub.call
        yield from _calls(sub)


def requires_session(route: RouteContext) -> bool:
    """상위 라우터의 의존성까지 합친 실제 의존성 안에 `get_current_session`이 있는가."""
    if not isinstance(route.original_route, APIRoute):
        return False
    return get_current_session in set(_calls(route.dependant))


def api_endpoints(app: FastAPI) -> list[tuple[str, str, RouteContext]]:
    """등록된 `/api/*` 라우트의 (메서드, 경로, 라우트) 목록.

    FastAPI는 포함된 라우터를 펼치지 않고 들고 있으므로, OpenAPI 생성과 같은
    `iter_route_contexts`로 상위 라우터의 경로 접두사·의존성을 합친 실제 라우트를 본다.
    """
    found: list[tuple[str, str, RouteContext]] = []
    for route in iter_route_contexts(app.routes):
        path = route.path or ""
        if not (path == "/api" or path.startswith("/api/")):
            continue
        # 메서드가 없는 라우트(Mount 등)는 "*"로 두어 검사에서 걸리게 한다.
        for method in sorted(route.methods or {"*"}):
            found.append((method, path, route))
    return found


def _docs_paths(app: FastAPI) -> set[str]:
    """OpenAPI 문서 경로 (로컬 개발에서 ENABLE_API_DOCS=1일 때만 있음, 운영에서는 기동 거부)."""
    paths = {app.docs_url, app.redoc_url, app.openapi_url}
    if app.docs_url and app.swagger_ui_oauth2_redirect_url:
        paths.add(app.swagger_ui_oauth2_redirect_url)
    return {p for p in paths if p}


def assert_default_deny(app: FastAPI) -> None:
    """공개 목록 밖의 `/api/*` 라우트가 모두 세션을 요구하는지 확인한다. 아니면 RuntimeError."""
    public_seen: set[tuple[str, str]] = set()
    docs = _docs_paths(app)
    for method, path, route in api_endpoints(app):
        key = (method, path)
        if path in docs and not isinstance(route.original_route, APIRoute):
            continue
        if key in PUBLIC_ENDPOINTS:
            if requires_session(route):
                raise RuntimeError(
                    f"공개 엔드포인트에 세션 의존성이 걸려 있습니다: {method} {path}"
                )
            public_seen.add(key)
        elif not requires_session(route):
            raise RuntimeError(f"인증 없이 열린 /api 라우트가 있습니다: {method} {path}")
    missing = PUBLIC_ENDPOINTS - public_seen
    if missing:
        raise RuntimeError(f"공개 엔드포인트가 등록되지 않았습니다: {sorted(missing)}")
