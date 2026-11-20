from fastapi.testclient import TestClient

from tests.conftest import (
    FAKE_PASSWORD,
    FAKE_USERNAME,
    FakeClock,
    do_setup,
    totp_now,
)


def _login_verify(client: TestClient, body: dict) -> int:
    device = TestClient(client.app, base_url="https://testserver")
    res = device.post(
        "/api/auth/login", json={"username": FAKE_USERNAME, "password": FAKE_PASSWORD}
    )
    assert res.status_code == 200
    return device.post(
        "/api/auth/login/verify", json={"challenge_id": res.json()["challenge_id"], **body}
    ).status_code


def _start_reset(client: TestClient, clock: FakeClock, secret: str) -> str:
    res = client.post(
        "/api/auth/totp/reset", json={"password": FAKE_PASSWORD, "code": totp_now(secret, clock)}
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["qr_data_url"].startswith("data:image/svg+xml;base64,")
    clock.advance(30)
    return data["secret"]


def test_totp_reset_full_flow(client: TestClient, clock: FakeClock) -> None:
    old_secret, old_codes = do_setup(client, clock)
    new_secret = _start_reset(client, clock, old_secret)
    assert new_secret != old_secret

    # 확정 전: 기존 TOTP·복구 코드가 계속 유효, 새 TOTP는 아직 아님
    assert _login_verify(client, {"code": totp_now(new_secret, clock)}) == 401
    assert _login_verify(client, {"code": totp_now(old_secret, clock)}) == 204
    clock.advance(30)
    assert _login_verify(client, {"recovery_code": old_codes[0]}) == 204

    res = client.post("/api/auth/totp/reset/verify", json={"code": totp_now(new_secret, clock)})
    assert res.status_code == 200
    new_codes = res.json()["recovery_codes"]
    assert len(new_codes) == 10
    clock.advance(30)

    # 확정 후: 새 TOTP만 유효, 기존 복구 코드는 모두 폐기, 새 복구 코드 유효
    assert _login_verify(client, {"code": totp_now(old_secret, clock)}) == 401
    assert _login_verify(client, {"recovery_code": old_codes[1]}) == 401
    assert _login_verify(client, {"recovery_code": new_codes[0]}) == 204
    assert _login_verify(client, {"code": totp_now(new_secret, clock)}) == 204

    # 현재 세션은 유지된다.
    assert client.get("/api/auth/sessions").status_code == 200


def test_totp_reset_wrong_password_or_code(client: TestClient, clock: FakeClock) -> None:
    secret, _ = do_setup(client, clock)
    res = client.post(
        "/api/auth/totp/reset",
        json={"password": "wrong-password-123", "code": totp_now(secret, clock)},
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_credentials"

    res = client.post("/api/auth/totp/reset", json={"password": FAKE_PASSWORD, "code": "abcdef"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_code"

    # 실패는 로그인 실패와 합산 → 5회면 429
    for _ in range(3):
        client.post("/api/auth/totp/reset", json={"password": FAKE_PASSWORD, "code": "abcdef"})
    res = client.post(
        "/api/auth/totp/reset", json={"password": FAKE_PASSWORD, "code": totp_now(secret, clock)}
    )
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "too_many_attempts"
    assert "retry-after" in res.headers


def test_totp_reset_verify_without_start(client: TestClient, clock: FakeClock) -> None:
    do_setup(client, clock)
    res = client.post("/api/auth/totp/reset/verify", json={"code": "123456"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "totp_reset_expired"


def test_totp_reset_pending_expires(client: TestClient, clock: FakeClock) -> None:
    secret, _ = do_setup(client, clock)
    new_secret = _start_reset(client, clock, secret)
    clock.advance(10 * 60)
    res = client.post("/api/auth/totp/reset/verify", json={"code": totp_now(new_secret, clock)})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "totp_reset_expired"


def test_totp_reset_pending_bound_to_session(client: TestClient, clock: FakeClock) -> None:
    secret, codes = do_setup(client, clock)
    new_secret = _start_reset(client, clock, secret)

    other = TestClient(client.app, base_url="https://testserver")
    res = other.post("/api/auth/login", json={"username": FAKE_USERNAME, "password": FAKE_PASSWORD})
    other.post(
        "/api/auth/login/verify",
        json={"challenge_id": res.json()["challenge_id"], "recovery_code": codes[0]},
    )
    res = other.post("/api/auth/totp/reset/verify", json={"code": totp_now(new_secret, clock)})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "totp_reset_expired"


def test_totp_reset_wrong_new_code(client: TestClient, clock: FakeClock) -> None:
    secret, _ = do_setup(client, clock)
    new_secret = _start_reset(client, clock, secret)
    res = client.post("/api/auth/totp/reset/verify", json={"code": "abcdef"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_code"
    # 대기 정보는 남아 있어 다시 시도할 수 있다.
    res = client.post("/api/auth/totp/reset/verify", json={"code": totp_now(new_secret, clock)})
    assert res.status_code == 200
