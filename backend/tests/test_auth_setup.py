import base64

from fastapi.testclient import TestClient

from tests.conftest import (
    FAKE_PASSWORD,
    FAKE_SETUP_TOKEN,
    FAKE_USERNAME,
    FakeClock,
    do_setup,
    totp_now,
)

SETUP_BODY = {"username": FAKE_USERNAME, "password": FAKE_PASSWORD, "setup_token": FAKE_SETUP_TOKEN}


def test_status_before_setup(client: TestClient) -> None:
    res = client.get("/api/auth/status")
    assert res.status_code == 200
    assert res.json() == {"setup_required": True, "logged_in": False}


def test_setup_full_flow(client: TestClient, clock: FakeClock) -> None:
    res = client.post("/api/auth/setup", json=SETUP_BODY)
    assert res.status_code == 200
    data = res.json()
    assert set(data) == {"qr_data_url", "secret"}
    assert data["qr_data_url"].startswith("data:image/svg+xml;base64,")
    svg = base64.b64decode(data["qr_data_url"].split(",", 1)[1])
    assert b"<svg" in svg

    # 대기 쿠키: HttpOnly, Secure, SameSite=Lax, __Host- 접두사, 10분
    set_cookie = res.headers["set-cookie"]
    assert set_cookie.startswith("__Host-setup=")
    for attr in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age=600"):
        assert attr in set_cookie

    # 확정 전에는 아직 사용자가 없다.
    assert client.get("/api/auth/status").json()["setup_required"] is True

    res = client.post("/api/auth/setup/verify", json={"code": totp_now(data["secret"], clock)})
    assert res.status_code == 200
    codes = res.json()["recovery_codes"]
    assert len(codes) == 10
    assert len(set(codes)) == 10

    cookies = res.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith("__Host-session="))
    for attr in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", f"Max-Age={400 * 86400}"):
        assert attr in session_cookie
    assert any(c.startswith("__Host-setup=") and "Max-Age=0" in c for c in cookies)

    assert client.get("/api/auth/status").json() == {"setup_required": False, "logged_in": True}

    # DB에는 해시만 저장된다.
    conn = client.app.state.db.connect()
    try:
        stored = [r[0] for r in conn.execute("SELECT code_hash FROM recovery_codes")]
        token_hashes = [r[0] for r in conn.execute("SELECT token_hash FROM sessions")]
        password_hash = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    finally:
        conn.close()
    assert len(stored) == 10
    assert not set(codes) & set(stored)
    session_token = client.cookies.get("__Host-session")
    assert session_token not in token_hashes
    assert password_hash.startswith("$argon2id$")
    assert FAKE_PASSWORD not in password_hash


def test_setup_disabled_after_confirmed(client: TestClient, clock: FakeClock) -> None:
    do_setup(client, clock)

    res = client.post("/api/auth/setup", json={**SETUP_BODY, "username": "other"})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "setup_disabled"

    res = client.post("/api/auth/setup/verify", json={"code": "123456"})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "setup_disabled"


def test_setup_verify_without_pending_cookie(client: TestClient) -> None:
    res = client.post("/api/auth/setup/verify", json={"code": "123456"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "setup_expired"


def test_setup_verify_from_other_browser(client: TestClient, clock: FakeClock) -> None:
    secret = client.post("/api/auth/setup", json=SETUP_BODY).json()["secret"]
    other = TestClient(client.app, base_url="https://testserver")
    res = other.post("/api/auth/setup/verify", json={"code": totp_now(secret, clock)})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "setup_expired"


def test_setup_pending_expires_after_10_minutes(client: TestClient, clock: FakeClock) -> None:
    secret = client.post("/api/auth/setup", json=SETUP_BODY).json()["secret"]
    clock.advance(10 * 60)
    res = client.post("/api/auth/setup/verify", json={"code": totp_now(secret, clock)})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "setup_expired"
    assert client.get("/api/auth/status").json()["setup_required"] is True


def test_setup_restart_replaces_pending(client: TestClient, clock: FakeClock) -> None:
    first = client.post("/api/auth/setup", json=SETUP_BODY).json()["secret"]
    second = client.post(
        "/api/auth/setup",
        json={**SETUP_BODY, "username": "renamed", "password": "different-password"},
    ).json()["secret"]
    assert first != second
    assert len(client.app.state.setup_pending) == 1

    # 이전 비밀값의 코드는 더 이상 통하지 않는다.
    res = client.post("/api/auth/setup/verify", json={"code": totp_now(first, clock)})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_code"

    res = client.post("/api/auth/setup/verify", json={"code": totp_now(second, clock)})
    assert res.status_code == 200

    conn = client.app.state.db.connect()
    try:
        assert [r[0] for r in conn.execute("SELECT username FROM users")] == ["renamed"]
    finally:
        conn.close()


def test_setup_wrong_code_keeps_pending(client: TestClient, clock: FakeClock) -> None:
    secret = client.post("/api/auth/setup", json=SETUP_BODY).json()["secret"]
    res = client.post("/api/auth/setup/verify", json={"code": "abcdef"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_code"
    res = client.post("/api/auth/setup/verify", json={"code": totp_now(secret, clock)})
    assert res.status_code == 200


def test_setup_input_validation(client: TestClient) -> None:
    for body in (
        {"username": "tester", "password": "short"},  # 10자 미만
        {"username": "   ", "password": FAKE_PASSWORD},
        {"username": "x" * 65, "password": FAKE_PASSWORD},
        {"username": "tester"},
        {"password": FAKE_PASSWORD},
    ):
        res = client.post("/api/auth/setup", json={**body, "setup_token": FAKE_SETUP_TOKEN})
        assert res.status_code == 400, body
        assert res.json()["error"]["code"] == "invalid_input"

    res = client.post("/api/auth/setup", json={**SETUP_BODY, "password": "a" * 10})
    assert res.status_code == 200


def test_setup_insecure_cookie_mode(make_client, clock: FakeClock, tmp_path) -> None:
    client = make_client(
        clock=clock, DB_PATH=str(tmp_path / "t.db"), COOKIE_SECURE="0", SITE_DOMAIN=""
    )
    client.base_url = "http://testserver"
    res = client.post("/api/auth/setup", json=SETUP_BODY)
    set_cookie = res.headers["set-cookie"]
    assert set_cookie.startswith("setup=")
    assert "Secure" not in set_cookie
    res = client.post(
        "/api/auth/setup/verify", json={"code": totp_now(res.json()["secret"], clock)}
    )
    assert res.status_code == 200
    assert "session" in client.cookies
    assert client.get("/api/auth/status").json()["logged_in"] is True
