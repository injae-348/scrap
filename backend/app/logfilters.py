"""로그 정리: 접근 로그에서 쿼리 문자열 빼기, 외부 라이브러리 로그 수준.

- uvicorn 접근 로그(`uvicorn.access`)는 요청 줄을 쿼리 문자열까지 남긴다. 검색어(`q`)·커서 같은 개인
  데이터가 컨테이너 로그에 쌓이지 않게 경로만 남긴다 (`GET /api/scraps?q=…` → `GET /api/scraps`).
  기동 명령 인자(`--no-access-log`, `--log-config` 등)와 상관없이 적용되도록 앱을 만들 때
  (`create_app()`) 로거에 필터를 단다. uvicorn은 로깅 설정을 마친 뒤에 앱을 불러오므로
  필터가 지워지지 않는다.
- 본문 추출·Claude SDK 라이브러리 로거는 WARNING 이상만 남긴다.
"""

import logging
import re

ACCESS_LOGGER = "uvicorn.access"
QUIET_LOGGERS = ("trafilatura", "htmldate", "anthropic")
# 인자 형식이 바뀌어 메시지 문자열에 요청 줄이 통째로 들어온 경우용: `"METHOD /경로?쿼리 HTTP/`.
_REQUEST_LINE_QUERY = re.compile(r'("[A-Z]+ /[^"?\s]*)\?[^"\s]*( HTTP/)')


def strip_query(path: str) -> str:
    """`/a/b?x=1` → `/a/b`."""
    return path.split("?", 1)[0]


class DropQueryStringFilter(logging.Filter):
    """접근 로그 레코드의 요청 경로에서 `?` 뒤를 지운다 (레코드는 버리지 않는다).

    uvicorn은 `('%s - "%s %s HTTP/%s" %d', 클라이언트, 메서드, 경로+쿼리, HTTP 버전, 상태)` 형식으로
    남기고, 접근 로그 포매터가 인자 튜플을 그대로 풀어 쓰므로 튜플 모양은 유지한다.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and args:
            record.args = tuple(
                strip_query(arg) if isinstance(arg, str) and arg.startswith("/") else arg
                for arg in args
            )
        elif not args and isinstance(record.msg, str):
            record.msg = _REQUEST_LINE_QUERY.sub(r"\1\2", record.msg)
        return True


def install_log_filters() -> None:
    """여러 번 불러도 필터는 하나만 단다 (테스트에서 앱을 여러 번 만든다)."""
    access = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(f, DropQueryStringFilter) for f in access.filters):
        access.addFilter(DropQueryStringFilter())
    for name in QUIET_LOGGERS:
        logger = logging.getLogger(name)
        if logger.level == logging.NOTSET or logger.level < logging.WARNING:
            logger.setLevel(logging.WARNING)
