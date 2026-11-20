"""CSRF 방어: 상태를 바꾸는 `/api/*` 요청의 출처 확인 (docs/API.md 인증 세부 규칙).

- GET·HEAD·OPTIONS가 아닌 요청에 `Origin`이 있으면 허용 출처와 같아야 한다.
  다르면 403 `origin_mismatch`.
- `Origin`이 없으면 `Sec-Fetch-Site`가 없거나 `same-origin`일 때만 허용한다.
세션 쿠키의 SameSite=Lax와 함께 쓴다 (Lax만으로는 같은 사이트의 다른 서브도메인 등을 막지 못한다).
"""

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import normalize_origin
from app.errors import error_response
from app.ratelimit import is_api_path

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def origin_allowed(headers: Headers, allowed_origins: frozenset[str]) -> bool:
    origin = headers.get("origin")
    if origin is not None:
        return normalize_origin(origin) in allowed_origins
    fetch_site = headers.get("sec-fetch-site")
    return fetch_site is None or fetch_site.strip().lower() == "same-origin"


class OriginCheckMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: frozenset[str]) -> None:
        self.app = app
        self.allowed_origins = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] not in SAFE_METHODS
            and is_api_path(scope["path"])
            and not origin_allowed(Headers(scope=scope), self.allowed_origins)
        ):
            response = error_response(403, "origin_mismatch", "허용되지 않은 출처의 요청입니다.")
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
