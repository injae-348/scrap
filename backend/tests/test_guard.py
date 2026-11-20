"""요청 본문 상한(앱 1MB, 공개 경로 16KB → 413)과 세션 확인이 본문 읽기보다 먼저인지."""

import asyncio
import json
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.guard import MAX_BODY_BYTES, PUBLIC_MAX_BODY_BYTES
from app.routing import PUBLIC_ENDPOINTS, api_endpoints
from tests.conftest import FakeClock

PAYLOAD_TOO_LARGE = {"error": {"code": "payload_too_large", "message": "요청 본문이 너무 큽니다."}}


def _protected(client: TestClient) -> list[tuple[str, str]]:
    return [
        (m, re.sub(r"\{[^}]+\}", "1", p))
        for m, p, _ in api_endpoints(client.app)
        if (m, p) not in PUBLIC_ENDPOINTS
    ]


def _json_body(size: int) -> bytes:
    """정확히 `size` 바이트인 JSON 본문 (스크랩 생성 형식)."""
    head = b'{"url":"https://example.test/","memo":"'
    tail = b'"}'
    return head + b"a" * (size - len(head) - len(tail)) + tail


# ── 직접 ASGI 호출 (본문을 얼마나 읽었는지 확인) ─────────────


class RawResult:
    def __init__(self) -> None:
        self.status: int | None = None
        self.body = b""
        self.headers: dict[str, str] = {}
        self.chunks_read = 0
        self.bytes_read = 0


def raw_request(
    client: TestClient,
    method: str,
    path: str,
    chunks: list[bytes],
    headers: dict[str, str] | None = None,
    content_length: bool = True,
) -> RawResult:
    """미들웨어까지 포함한 앱을 직접 부른다. `receive`가 넘겨준 조각 수·바이트 수를 센다."""
    result = RawResult()
    raw_headers = [(b"host", b"testserver")]
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode(), value.encode()))
    if content_length:
        raw_headers.append((b"content-length", str(sum(map(len, chunks))).encode()))
    else:
        raw_headers.append((b"transfer-encoding", b"chunked"))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": raw_headers,
        "client": ("203.0.113.9", 50000),
        "server": ("testserver", 443),
    }
    pending = list(chunks)

    async def receive() -> dict:
        if not pending:
            await asyncio.sleep(3600)  # 클라이언트가 더 보내지 않음
        chunk = pending.pop(0)
        result.chunks_read += 1
        result.bytes_read += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": bool(pending)}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.start":
            result.status = message["status"]
            result.headers = {k.decode(): v.decode() for k, v in message["headers"]}
        elif message["type"] == "http.response.body":
            result.body += message.get("body", b"")

    asyncio.run(asyncio.wait_for(client.app(scope, receive, send), timeout=10))
    return result


def _chunks(total: int, size: int = 64 * 1024) -> list[bytes]:
    body = _json_body(total)
    return [body[i : i + size] for i in range(0, len(body), size)]


# ── 세션 확인이 본문보다 먼저 ──────────────────────────


def test_malformed_json_without_session_is_401(client: TestClient) -> None:
    for method, path in _protected(client):
        res = client.request(
            method, path, content=b'{"broken', headers={"Content-Type": "application/json"}
        )
        assert res.status_code == 401, (method, path, res.text)
        assert res.json()["error"]["code"] == "unauthorized"


def test_large_body_without_session_is_401_and_not_read(client: TestClient) -> None:
    for content_length in (True, False):
        result = raw_request(
            client,
            "POST",
            "/api/scraps",
            _chunks(2 * MAX_BODY_BYTES),
            headers={"content-type": "application/json"},
            content_length=content_length,
        )
        assert result.status == 401
        assert json.loads(result.body)["error"]["code"] == "unauthorized"
        assert result.bytes_read == 0  # 본문을 한 바이트도 읽지 않았다


def test_forged_cookie_large_body_is_401(client: TestClient) -> None:
    result = raw_request(
        client,
        "PATCH",
        "/api/sources/1",
        _chunks(2 * MAX_BODY_BYTES),
        headers={"content-type": "application/json", "cookie": "__Host-session=forged"},
    )
    assert result.status == 401
    assert result.bytes_read == 0


def test_expired_session_is_401_before_body(user: TestClient, clock: FakeClock) -> None:
    clock.advance(181 * 24 * 60 * 60)
    res = user.post("/api/scraps", content=b"{", headers={"Content-Type": "application/json"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_protected_route_503_when_db_missing(make_client, tmp_path) -> None:
    client = make_client(DB_PATH=str(tmp_path / "missing" / "t.db"))
    client.cookies.set("__Host-session", "anything")
    res = client.post("/api/scraps", json={"url": "https://example.test"})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "db_unavailable"


# ── 본문 상한 ───────────────────────────────────────


def test_logged_in_body_over_1mb_is_413(user: TestClient) -> None:
    headers = {"Content-Type": "application/json"}
    at_limit = user.post("/api/scraps", content=_json_body(MAX_BODY_BYTES), headers=headers)
    assert at_limit.status_code == 400  # 상한 안: 본문 검사까지 간다 (메모 100,000자 초과)
    over = user.post("/api/scraps", content=_json_body(MAX_BODY_BYTES + 1), headers=headers)
    assert over.status_code == 413
    assert over.json() == PAYLOAD_TOO_LARGE
    assert over.headers["cache-control"] == "no-store"


def test_logged_in_chunked_body_over_1mb_is_413(user: TestClient) -> None:
    cookie = f"__Host-session={user.cookies.get('__Host-session')}"
    result = raw_request(
        user,
        "POST",
        "/api/scraps",
        _chunks(3 * MAX_BODY_BYTES),
        headers={"content-type": "application/json", "cookie": cookie},
        content_length=False,
    )
    assert result.status == 413
    assert json.loads(result.body) == PAYLOAD_TOO_LARGE
    # 넘는 순간 멈춘다 (3MB를 끝까지 읽지 않음)
    assert result.bytes_read <= MAX_BODY_BYTES + 64 * 1024


def test_logged_in_content_length_over_limit_not_read(user: TestClient) -> None:
    cookie = f"__Host-session={user.cookies.get('__Host-session')}"
    result = raw_request(
        user,
        "POST",
        "/api/scraps",
        _chunks(MAX_BODY_BYTES + 1),
        headers={"content-type": "application/json", "cookie": cookie},
    )
    assert result.status == 413
    assert result.bytes_read == 0


def test_testclient_generator_body_over_limit(user: TestClient) -> None:
    def gen() -> Iterator[bytes]:
        yield from _chunks(2 * MAX_BODY_BYTES)

    res = user.post("/api/scraps", content=gen(), headers={"Content-Type": "application/json"})
    assert res.status_code == 413


@pytest.mark.parametrize("path", ["/api/auth/login", "/api/auth/setup", "/api/auth/login/verify"])
def test_public_path_body_over_16kb_is_413(client: TestClient, path: str) -> None:
    headers = {"Content-Type": "application/json"}
    over = client.post(path, content=b" " * (PUBLIC_MAX_BODY_BYTES + 1), headers=headers)
    assert over.status_code == 413
    assert over.json() == PAYLOAD_TOO_LARGE

    result = raw_request(
        client,
        "POST",
        path,
        [b" " * 8192] * 3,
        headers={"content-type": "application/json"},
        content_length=False,
    )
    assert result.status == 413


def test_public_path_body_within_16kb_ok(client: TestClient) -> None:
    body = json.dumps({"username": "x" * 100, "password": "p" * 1000}).encode()
    body += b" " * (PUBLIC_MAX_BODY_BYTES - len(body))
    res = client.post("/api/auth/login", content=body, headers={"Content-Type": "application/json"})
    assert res.status_code == 401  # 상한 안: 로그인 처리까지 간다
    assert res.json()["error"]["code"] == "invalid_credentials"


def test_unregistered_paths_are_404(client: TestClient) -> None:
    for method in ("GET", "POST", "DELETE"):
        res = client.request(method, "/api/nope", content=b"{")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"
    assert client.get("/api/scraps/1/nope").status_code == 404


def test_path_id_rules(user: TestClient) -> None:
    for path in ("/api/scraps/abc", "/api/scraps/1.5"):
        res = user.get(path)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "invalid_input"
    assert user.patch("/api/topics/abc", json={"name": "a"}).status_code == 400
    assert user.delete("/api/sources/x").status_code == 400
    for path in ("/api/scraps/999", "/api/scraps/0", "/api/scraps/-1"):
        assert user.get(path).status_code == 404
    assert (
        TestClient(user.app, base_url="https://testserver").get("/api/scraps/abc").status_code
        == 401
    )
