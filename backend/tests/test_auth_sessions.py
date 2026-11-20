import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from app.auth import CurrentSession, get_current_session
from tests.conftest import FakeClock, do_login, do_setup

DAY = 24 * 60 * 60

PROTECTED = [
    ("post", "/api/auth/logout"),
    ("post", "/api/auth/logout-all"),
    ("get", "/api/auth/sessions"),
    ("delete", "/api/auth/sessions/1"),
    ("post", "/api/auth/totp/reset"),
    ("post", "/api/auth/totp/reset/verify"),
]


def _device(client: TestClient, ua: str) -> TestClient:
    return TestClient(client.app, base_url="https://testserver", headers={"User-Agent": ua})


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_protected_endpoints_401_without_session(
    client: TestClient, method: str, path: str
) -> None:
    kwargs = {"json": {"password": "x", "code": "123456"}} if "totp" in path else {}
    res = client.request(method.upper(), path, **kwargs)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_invalid_session_cookie_401(client: TestClient) -> None:
    client.cookies.set("__Host-session", "forged-token")
    assert client.get("/api/auth/sessions").status_code == 401
    assert client.get("/api/auth/status").json()["logged_in"] is False


def test_sessions_list_and_current(client: TestClient, clock: FakeClock) -> None:
    secret, _ = do_setup(client, clock)
    phone = _device(client, "FakePhone/1.0")
    do_login(phone, clock, secret)

    res = phone.get("/api/auth/sessions")
    assert res.status_code == 200
    sessions = res.json()
    assert len(sessions) == 2
    for s in sessions:
        assert set(s) == {"id", "user_agent", "created_at", "last_seen_at", "current"}
        assert s["created_at"].endswith("+09:00")
    current = [s for s in sessions if s["current"]]
    assert len(current) == 1
    assert current[0]["user_agent"] == "FakePhone/1.0"

    # 원래 기기에서 보면 current가 바뀐다.
    mine = [s for s in client.get("/api/auth/sessions").json() if s["current"]]
    assert mine[0]["id"] != current[0]["id"]


def test_logout_deletes_only_current(client: TestClient, clock: FakeClock) -> None:
    secret, _ = do_setup(client, clock)
    phone = _device(client, "FakePhone/1.0")
    do_login(phone, clock, secret)

    res = phone.post("/api/auth/logout")
    assert res.status_code == 204
    cookies = res.headers.get_list("set-cookie")
    assert len(cookies) == 1  # 갱신 쿠키 없이 삭제 쿠키만
    assert cookies[0].startswith("__Host-session=") and "Max-Age=0" in cookies[0]
    assert "Secure" in cookies[0]

    assert phone.get("/api/auth/sessions").status_code == 401
    assert client.get("/api/auth/sessions").status_code == 200
    assert len(client.get("/api/auth/sessions").json()) == 1


def test_logout_all_deletes_every_session(client: TestClient, clock: FakeClock) -> None:
    secret, _ = do_setup(client, clock)
    phone = _device(client, "FakePhone/1.0")
    do_login(phone, clock, secret)

    assert client.post("/api/auth/logout-all").status_code == 204
    assert client.get("/api/auth/sessions").status_code == 401
    assert phone.get("/api/auth/sessions").status_code == 401


def test_delete_other_session(client: TestClient, clock: FakeClock) -> None:
    secret, _ = do_setup(client, clock)
    phone = _device(client, "FakePhone/1.0")
    do_login(phone, clock, secret)
    phone_id = next(s["id"] for s in phone.get("/api/auth/sessions").json() if s["current"])

    res = client.delete(f"/api/auth/sessions/{phone_id}")
    assert res.status_code == 204
    assert phone.get("/api/auth/sessions").status_code == 401
    assert client.get("/api/auth/sessions").status_code == 200

    # 이미 없는 세션
    res = client.delete(f"/api/auth/sessions/{phone_id}")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"
    assert client.delete("/api/auth/sessions/99999").status_code == 404
    assert client.delete("/api/auth/sessions/abc").status_code == 400


def test_delete_own_session_clears_cookie(client: TestClient, clock: FakeClock) -> None:
    do_setup(client, clock)
    my_id = client.get("/api/auth/sessions").json()[0]["id"]
    res = client.delete(f"/api/auth/sessions/{my_id}")
    assert res.status_code == 204
    assert "Max-Age=0" in res.headers["set-cookie"]
    assert client.get("/api/auth/sessions").status_code == 401


def test_session_cookie_refreshed_on_each_request(client: TestClient, clock: FakeClock) -> None:
    do_setup(client, clock)
    res = client.get("/api/auth/sessions")
    set_cookie = res.headers["set-cookie"]
    assert set_cookie.startswith("__Host-session=")
    assert f"Max-Age={400 * DAY}" in set_cookie


def test_last_seen_updated_at_most_hourly(client: TestClient, clock: FakeClock) -> None:
    do_setup(client, clock)
    first = client.get("/api/auth/sessions").json()[0]["last_seen_at"]
    clock.advance(30 * 60)
    assert client.get("/api/auth/sessions").json()[0]["last_seen_at"] == first
    clock.advance(30 * 60)
    assert client.get("/api/auth/sessions").json()[0]["last_seen_at"] != first


def test_session_expires_after_180_days_idle(client: TestClient, clock: FakeClock) -> None:
    do_setup(client, clock)
    clock.advance(179 * DAY)
    assert client.get("/api/auth/sessions").status_code == 200  # 사용 → 갱신
    clock.advance(179 * DAY)
    assert client.get("/api/auth/sessions").status_code == 200
    clock.advance(180 * DAY)
    res = client.get("/api/auth/sessions")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"

    # 만료된 세션은 DB에서도 지워진다.
    conn = client.app.state.db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    finally:
        conn.close()


def test_rotating_session_secret_invalidates_sessions(
    make_client, clock: FakeClock, tmp_path
) -> None:
    db = str(tmp_path / "t.db")
    client = make_client(clock=clock, DB_PATH=db)
    do_setup(client, clock)
    token = client.cookies.get("__Host-session")

    rotated = make_client(clock=clock, DB_PATH=db, SESSION_SECRET="another-fake-secret-" + "y" * 20)
    rotated.cookies.set("__Host-session", token)
    assert rotated.get("/api/auth/sessions").status_code == 401


def test_get_current_session_dependency_reusable(client: TestClient, clock: FakeClock) -> None:
    # Phase 5 라우터가 쓰는 방식
    router = APIRouter(prefix="/api", dependencies=[Depends(get_current_session)])

    @router.get("/_whoami")
    def whoami(session: CurrentSession = Depends(get_current_session)) -> dict[str, int]:  # noqa: B008
        return {"user_id": session.user_id}

    client.app.include_router(router)
    assert client.get("/api/_whoami").status_code == 401
    do_setup(client, clock)
    assert client.get("/api/_whoami").json() == {"user_id": 1}
