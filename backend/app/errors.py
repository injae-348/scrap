"""오류 응답을 docs/API.md 공통 형식으로 맞춘다.

    { "error": { "code": "string", "message": "사용자에게 보여줄 한국어 문구" } }

FastAPI 기본 형식(`{"detail": ...}`)이 그대로 나가지 않도록 전역 핸들러를 둔다.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app")

# 상태 코드별 기본 code / message. 라우트에서 ApiError로 직접 지정하면 그 값을 쓴다.
_DEFAULTS: dict[int, tuple[str, str]] = {
    400: ("invalid_input", "입력값이 올바르지 않습니다."),
    401: ("unauthorized", "로그인이 필요합니다."),
    403: ("forbidden", "권한이 없습니다."),
    404: ("not_found", "요청한 항목을 찾을 수 없습니다."),
    405: ("method_not_allowed", "허용되지 않는 요청 방식입니다."),
    413: ("payload_too_large", "요청 본문이 너무 큽니다."),
    429: ("too_many_requests", "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."),
    500: ("internal_error", "서버 오류가 발생했습니다."),
    503: ("service_unavailable", "서비스를 일시적으로 사용할 수 없습니다."),
}


class ApiError(Exception):
    """라우트에서 API.md 형식의 오류를 내기 위한 예외."""

    def __init__(
        self,
        status_code: int,
        code: str | None = None,
        message: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        default_code, default_message = _DEFAULTS.get(
            status_code, ("error", "오류가 발생했습니다.")
        )
        self.status_code = status_code
        self.code = code or default_code
        self.message = message or default_message
        self.headers = headers
        super().__init__(self.message)


def error_response(
    status_code: int,
    code: str | None = None,
    message: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    err = ApiError(status_code, code, message, headers)
    return JSONResponse(
        status_code=err.status_code,
        content={"error": {"code": err.code, "message": err.message}},
        headers=err.headers,
    )


async def _handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.headers)


async def _handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    # Starlette 기본 detail(영문)은 사용자 문구로 쓰지 않고 상태 코드별 한국어 문구를 쓴다.
    return error_response(exc.status_code, headers=getattr(exc, "headers", None))


async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # API.md는 입력 오류를 400으로 정한다 (FastAPI 기본 422 대신).
    return error_response(400)


async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("처리되지 않은 예외", exc_info=exc)
    return error_response(500)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _handle_api_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected)
