"""접근 로그에서 쿼리 문자열(검색어·커서) 빼기."""

import copy
import io
import logging
import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
from uvicorn.config import LOGGING_CONFIG
from uvicorn.logging import AccessFormatter

from app.logfilters import ACCESS_LOGGER, DropQueryStringFilter, install_log_filters
from app.main import create_app
from tests.conftest import FAKE_SESSION_SECRET

PRIVATE_QUERY = "q=비밀검색어&cursor=eyJjdXJzb3IiOjF9"


@pytest.fixture
def access_logger() -> Iterator[logging.Logger]:
    """uvicorn 로거 상태를 테스트 뒤에 되돌린다."""
    names = ("uvicorn", "uvicorn.error", "uvicorn.access")
    saved = {}
    for name in names:
        lg = logging.getLogger(name)
        saved[name] = (lg.level, lg.propagate, list(lg.handlers), list(lg.filters))
    yield logging.getLogger(ACCESS_LOGGER)
    for name, (level, propagate, handlers, filters) in saved.items():
        lg = logging.getLogger(name)
        lg.setLevel(level)
        lg.propagate = propagate
        lg.handlers[:] = handlers
        lg.filters[:] = filters


def _capture(logger: logging.Logger) -> io.StringIO:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return buf


def test_filter_strips_query_from_uvicorn_record(access_logger: logging.Logger) -> None:
    install_log_filters()
    install_log_filters()  # 여러 번 불러도 하나만
    assert sum(isinstance(f, DropQueryStringFilter) for f in access_logger.filters) == 1
    buf = _capture(access_logger)
    # uvicorn(h11·httptools)이 남기는 형식 그대로
    access_logger.info(
        '%s - "%s %s HTTP/%s" %d',
        "203.0.113.5:1234",
        "GET",
        f"/api/scraps?{PRIVATE_QUERY}",
        "1.1",
        200,
    )
    access_logger.info('%s - "%s %s HTTP/%s" %d', "203.0.113.5:1", "GET", "/api/health", "1.1", 200)
    out = buf.getvalue()
    assert '"GET /api/scraps HTTP/1.1" 200' in out
    assert '"GET /api/health HTTP/1.1" 200' in out
    assert "비밀검색어" not in out and "cursor" not in out and "?" not in out


def test_filter_handles_preformatted_message() -> None:
    record = logging.LogRecord(
        ACCESS_LOGGER,
        logging.INFO,
        __file__,
        1,
        f'1.2.3.4 - "GET /api/scraps?{PRIVATE_QUERY} HTTP/1.1" 200',
        None,
        None,
    )
    assert DropQueryStringFilter().filter(record) is True
    assert record.getMessage() == '1.2.3.4 - "GET /api/scraps HTTP/1.1" 200'


def test_create_app_installs_filter(make_client, tmp_path, access_logger) -> None:
    access_logger.filters[:] = []
    make_client(DB_PATH=str(tmp_path / "t.db"))
    assert any(isinstance(f, DropQueryStringFilter) for f in access_logger.filters)
    for name in ("trafilatura", "htmldate", "anthropic"):
        assert logging.getLogger(name).level == logging.WARNING


def _app_factory():  # uvicorn --factory 용
    return create_app()


@pytest.mark.parametrize("http", ["h11", "httptools"])
def test_real_uvicorn_access_log_has_no_query(
    clean_env, tmp_path, access_logger: logging.Logger, http: str
) -> None:
    """실제 uvicorn 기동 순서(로깅 설정 → 앱 불러오기)로 띄워 접근 로그를 확인한다."""
    clean_env.setenv("SESSION_SECRET", FAKE_SESSION_SECRET)
    clean_env.setenv("DB_PATH", str(tmp_path / "t.db"))
    access_logger.filters[:] = []  # 앱을 불러올 때 다시 달리는지 본다

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(
        "tests.test_logfilters:_app_factory",
        factory=True,
        http=http,
        loop="asyncio",
        log_config=copy.deepcopy(LOGGING_CONFIG),  # uvicorn 기본 로깅 설정 (dictConfig)
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            assert time.monotonic() < deadline, "uvicorn 이 시작되지 않음"
            time.sleep(0.02)
        buf = _capture(access_logger)
        with httpx.Client(trust_env=False, timeout=5) as client:
            assert client.get(f"http://127.0.0.1:{port}/api/health?{PRIVATE_QUERY}").status_code
            client.get(f"http://127.0.0.1:{port}/api/scraps?{PRIVATE_QUERY}")
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
    out = buf.getvalue()
    assert '"GET /api/health HTTP/1.1"' in out
    assert '"GET /api/scraps HTTP/1.1" 401' in out
    assert "비밀검색어" not in out and "cursor=" not in out
