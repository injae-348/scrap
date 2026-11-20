"""`/api/*` 응답 공통 헤더.

`Cache-Control: no-store`: TOTP 비밀값·QR·복구 코드·기기 목록 같은 인증 응답이
브라우저 디스크 캐시나 서비스워커 캐시에 남지 않게 한다 (docs/API.md 세션 쿠키 항목).
미들웨어가 앞에서 끊은 429·403 응답에도 붙도록 가장 바깥에 둔다.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.ratelimit import is_api_path


class NoStoreMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_api_path(scope["path"]):
            await self.app(scope, receive, send)
            return

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_header)
