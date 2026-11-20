import pytest
from fastapi.testclient import TestClient

from app.config import DEFAULT_REQUESTS_PER_MINUTE
from tests.conftest import FAKE_PASSWORD, FAKE_SETUP_TOKEN, SITE_ORIGIN, FakeClock

SETUP_BODY = {"username": "tester", "password": FAKE_PASSWORD, "setup_token": FAKE_SETUP_TOKEN}

# ── CSRF (Origin 검사) ─────────────────────────────────


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example.test"},
        {"Origin": "null"},
        {"Origin": "http://scrap.example.test"},  # 스킴이 다름
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ],
)
def test_cross_origin_post_rejected(client: TestClient, headers: dict[str, str]) -> None:
    res = client.post("/api/auth/setup", json=SETUP_BODY, headers=headers)
    assert res.status_code == 403
    assert res.json() == {
        "error": {"code": "origin_mismatch", "message": "허용되지 않은 출처의 요청입니다."}
    }
    assert len(client.app.state.setup_pending) == 0


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": SITE_ORIGIN},
        {"Origin": SITE_ORIGIN.upper() + "/"},
        {"Sec-Fetch-Site": "same-origin"},
        {},  # Origin·Sec-Fetch-Site 모두 없음 (curl 등)
    ],
)
def test_same_origin_post_allowed(client: TestClient, headers: dict[str, str]) -> None:
    res = client.post("/api/auth/setup", json=SETUP_BODY, headers=headers)
    assert res.status_code == 200


def test_safe_methods_not_checked(client: TestClient) -> None:
    res = client.get("/api/auth/status", headers={"Origin": "https://evil.example.test"})
    assert res.status_code == 200


def test_csrf_applies_to_delete(client: TestClient) -> None:
    res = client.delete("/api/auth/sessions/1", headers={"Origin": "https://evil.example.test"})
    assert res.status_code == 403


def test_dev_allowed_origins(make_client, tmp_path) -> None:
    client = make_client(
        DB_PATH=str(tmp_path / "t.db"), ALLOWED_ORIGINS="http://localhost:5173", SITE_DOMAIN=""
    )
    ok = client.post(
        "/api/auth/setup", json=SETUP_BODY, headers={"Origin": "http://localhost:5173"}
    )
    assert ok.status_code == 200
    bad = client.post(
        "/api/auth/setup", json=SETUP_BODY, headers={"Origin": "http://localhost:3000"}
    )
    assert bad.status_code == 403


# ── 공통 요청 제한 ────────────────────────────────────


def test_default_limit_value(client: TestClient) -> None:
    assert client.app.state.request_limiter.limit == DEFAULT_REQUESTS_PER_MINUTE == 300


def test_common_rate_limit(client: TestClient, clock: FakeClock) -> None:
    client.app.state.request_limiter.limit = 5
    for _ in range(5):
        assert client.get("/api/health").status_code == 200

    res = client.get("/api/health")
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "too_many_requests"
    assert res.headers["retry-after"] == "60"

    # 인증 API도 같은 상한
    assert client.get("/api/auth/status").status_code == 429

    clock.advance(45)
    assert client.get("/api/health").headers["retry-after"] == "15"
    clock.advance(15)
    assert client.get("/api/health").status_code == 200


def test_common_rate_limit_is_per_ip(client: TestClient) -> None:
    client.app.state.request_limiter.limit = 2
    for _ in range(3):
        client.get("/api/health")
    assert client.get("/api/health").status_code == 429

    other = TestClient(client.app, base_url="https://testserver", client=("198.51.100.8", 1234))
    assert other.get("/api/health").status_code == 200


def test_common_rate_limit_ignores_x_forwarded_for(client: TestClient) -> None:
    # 앱은 X-Forwarded-For 를 직접 읽지 않는다 (uvicorn --proxy-headers 가 신뢰 프록시만 반영).
    client.app.state.request_limiter.limit = 2
    for i in range(3):
        client.get("/api/health", headers={"X-Forwarded-For": f"203.0.113.{i}"})
    assert client.get("/api/health").status_code == 429


def test_rate_limit_only_on_api_paths(client: TestClient) -> None:
    client.app.state.request_limiter.limit = 1
    for _ in range(3):
        assert client.get("/nope").status_code == 404


def test_rate_limiter_store_is_bounded(client: TestClient) -> None:
    limiter = client.app.state.request_limiter
    limiter.max_keys = 10
    for i in range(50):
        limiter.hit(f"192.0.2.{i}")
    assert len(limiter._windows) <= 10

    login = client.app.state.login_limiter
    login.max_keys = 10
    for i in range(50):
        login.record_failure(f"192.0.2.{i}")
    assert len(login._entries) <= 10
