"""요청 본문 상한 + 세션 사전 확인 (docs/API.md v1.3 "공통").

순수 ASGI 미들웨어로, 라우터 바로 바깥(사용자 미들웨어 중 가장 안쪽)에 둔다.

1. 요청 경로를 등록된 라우트와 맞춰 본다 (FastAPI 라우터와 같은 `matches` 사용).
   - 세션이 필요한 라우트(`app.routing.requires_session`)면 **본문을 읽기 전에** 세션을 확인한다.
     쿠키가 없거나 무효·만료면 본문 형식·크기와 상관없이 401 `unauthorized`.
     세션 쿠키 갱신과 `CurrentSession` 값은 라우트 의존성(`get_current_session`)이 그대로 맡는다.
   - 공개 엔드포인트(`PUBLIC_ENDPOINTS`)는 본문 상한 16KB, 그 밖은 1MB.
   - 등록되지 않은 경로·허용되지 않은 메서드는 그대로 라우터에 넘겨 404/405가 되게 한다.
2. 본문 상한: `Content-Length`가 상한을 넘으면 앱을 부르지 않고 413 `payload_too_large`.
   `Content-Length`가 없는(chunked) 본문은 받는 만큼 세다가 넘는 순간 413.

FastAPI의 `max_body_size`(Starlette `RequestBodyLimitMiddleware`)를 쓰지 않는 이유: 본문을 읽지 않고
응답하는 경우(401·404)에도 `Content-Length`가 크면 응답을 일반 텍스트 413으로 바꿔 보내므로,
"세션이 없으면 401"과 공통 오류 형식을 지킬 수 없다.
"""

from typing import Any

from fastapi import FastAPI, Response
from fastapi.routing import RouteContext, iter_route_contexts
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.sessions import resolve_session
from app.db import Database, DatabaseUnavailableError
from app.errors import error_response
from app.ratelimit import is_api_path
from app.routing import PUBLIC_ENDPOINTS, requires_session

MAX_BODY_BYTES = 1024 * 1024
PUBLIC_MAX_BODY_BYTES = 16 * 1024


class BodyTooLargeError(StarletteHTTPException):
    """본문 상한 초과. 라우트 안에서 본문을 읽다가 나면 공통 오류 처리기가 413으로 바꾼다."""

    def __init__(self) -> None:
        super().__init__(status_code=413)


def payload_too_large() -> Response:
    return error_response(413, "payload_too_large", "요청 본문이 너무 큽니다.")


class RequestGuardMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        api: FastAPI,
        max_body: int = MAX_BODY_BYTES,
        public_max_body: int = PUBLIC_MAX_BODY_BYTES,
    ) -> None:
        self.app = app
        self.api = api
        self.max_body = max_body
        self.public_max_body = public_max_body
        # (라우트 객체 id, 경로 템플릿) → 세션 필요 여부. 의존성 트리 탐색을 요청마다 하지 않는다.
        self._needs_session: dict[tuple[int, str], bool] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self.max_body
        if is_api_path(scope["path"]):
            route = self._match(scope)
            if route is not None:
                if (scope["method"], route.path) in PUBLIC_ENDPOINTS:
                    limit = self.public_max_body
                elif self._route_needs_session(route):
                    rejection = await run_in_threadpool(self._check_session, scope)
                    if rejection is not None:
                        await rejection(scope, receive, send)
                        return

        length = _content_length(scope)
        if length is not None and length > limit:
            await payload_too_large()(scope, receive, send)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise BodyTooLargeError
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLargeError:
            # 보통은 라우트 안의 오류 처리기가 413을 보낸다.
            # 그 밖에서 났고 아직 응답 전이면 여기서 보낸다.
            if started:
                raise
            await payload_too_large()(scope, receive, send)

    def _match(self, scope: Scope) -> RouteContext | None:
        for route in iter_route_contexts(self.api.routes):
            match, _ = route.matches(scope)
            if match == Match.FULL:
                return route
        return None

    def _route_needs_session(self, route: RouteContext) -> bool:
        key = (id(route.original_route), route.path or "")
        cached = self._needs_session.get(key)
        if cached is None:
            cached = self._needs_session[key] = requires_session(route)
        return cached

    def _check_session(self, scope: Scope) -> Any:
        """세션이 유효하면 None, 아니면 보낼 오류 응답. (스레드풀에서 실행: SQLite 동기 I/O)"""
        database: Database = self.api.state.db
        try:
            conn = database.connect()
        except DatabaseUnavailableError:
            return error_response(503, "db_unavailable", "데이터베이스에 연결할 수 없습니다.")
        try:
            session = resolve_session(Request(scope), Response(), conn)
        finally:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            conn.close()
        if session is None:
            return error_response(401, "unauthorized", "로그인이 필요합니다.")
        return None


def _content_length(scope: Scope) -> int | None:
    value = Headers(scope=scope).get("content-length")
    if value is None:
        return None
    value = value.strip()
    return int(value) if value.isascii() and value.isdigit() else None
