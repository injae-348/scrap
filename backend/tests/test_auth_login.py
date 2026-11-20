import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    FAKE_PASSWORD,
    FAKE_USERNAME,
    FakeClock,
    do_setup,
    totp_now,
)

LOGIN_BODY = {"username": FAKE_USERNAME, "password": FAKE_PASSWORD}


@pytest.fixture
def registered(client: TestClient, clock: FakeClock) -> tuple[TestClient, str, list[str]]:
    """가입을 마친 뒤, 쿠키가 없는 새 기기(TestClient)를 돌려준다."""
    secret, codes = do_setup(client, clock)
    device = TestClient(client.app, base_url="https://testserver")
    return device, secret, codes


def _challenge(device: TestClient) -> str:
    res = device.post("/api/auth/login", json=LOGIN_BODY)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["totp_required"] is True
    return body["challenge_id"]


def test_login_with_totp(registered, clock: FakeClock) -> None:
    device, secret, _ = registered
    assert device.get("/api/auth/status").json()["logged_in"] is False

    challenge_id = _challenge(device)
    # 비밀번호만으로는 로그인되지 않는다.
    assert device.get("/api/auth/sessions").status_code == 401

    res = device.post(
        "/api/auth/login/verify",
        json={"challenge_id": challenge_id, "code": totp_now(secret, clock)},
    )
    assert res.status_code == 204
    assert res.content == b""
    assert res.headers["set-cookie"].startswith("__Host-session=")
    assert device.get("/api/auth/status").json()["logged_in"] is True
    assert device.get("/api/auth/sessions").status_code == 200


def test_totp_adjacent_window_allowed(registered, clock: FakeClock) -> None:
    device, secret, _ = registered
    previous_code = totp_now(secret, clock)
    clock.advance(30)  # 이전 구간 코드도 받는다
    res = device.post(
        "/api/auth/login/verify", json={"challenge_id": _challenge(device), "code": previous_code}
    )
    assert res.status_code == 204


def test_totp_too_old_rejected(registered, clock: FakeClock) -> None:
    device, secret, _ = registered
    old_code = totp_now(secret, clock)
    clock.advance(90)
    res = device.post(
        "/api/auth/login/verify", json={"challenge_id": _challenge(device), "code": old_code}
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_code"


def test_totp_reuse_rejected(registered, clock: FakeClock) -> None:
    device, secret, _ = registered
    code = totp_now(secret, clock)
    res = device.post(
        "/api/auth/login/verify", json={"challenge_id": _challenge(device), "code": code}
    )
    assert res.status_code == 204

    other = TestClient(device.app, base_url="https://testserver")
    res = other.post(
        "/api/auth/login/verify", json={"challenge_id": _challenge(other), "code": code}
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_code"


def test_login_with_recovery_code_once(registered) -> None:
    device, _, codes = registered
    # 대소문자·하이픈·공백 무시
    messy = " " + codes[0].lower().replace("-", " ") + " "
    res = device.post(
        "/api/auth/login/verify", json={"challenge_id": _challenge(device), "recovery_code": messy}
    )
    assert res.status_code == 204

    # 1회용
    res = device.post(
        "/api/auth/login/verify",
        json={"challenge_id": _challenge(device), "recovery_code": codes[0]},
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_code"

    # 다른 코드는 그대로 쓸 수 있다.
    res = device.post(
        "/api/auth/login/verify",
        json={"challenge_id": _challenge(device), "recovery_code": codes[1].replace("-", "")},
    )
    assert res.status_code == 204


def test_challenge_is_single_use(registered, clock: FakeClock) -> None:
    device, secret, codes = registered
    challenge_id = _challenge(device)
    res = device.post(
        "/api/auth/login/verify",
        json={"challenge_id": challenge_id, "code": totp_now(secret, clock)},
    )
    assert res.status_code == 204
    res = device.post(
        "/api/auth/login/verify", json={"challenge_id": challenge_id, "recovery_code": codes[0]}
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "challenge_expired"


def test_challenge_expires_after_5_minutes(registered, clock: FakeClock) -> None:
    device, secret, _ = registered
    challenge_id = _challenge(device)
    clock.advance(5 * 60)
    res = device.post(
        "/api/auth/login/verify",
        json={"challenge_id": challenge_id, "code": totp_now(secret, clock)},
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "challenge_expired"


def test_unknown_challenge(registered) -> None:
    device, _, _ = registered
    res = device.post("/api/auth/login/verify", json={"challenge_id": "nope", "code": "123456"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "challenge_expired"


def test_challenge_discarded_after_5_wrong_codes(registered, clock: FakeClock) -> None:
    device, secret, _ = registered
    challenge_id = _challenge(device)
    for _ in range(5):
        res = device.post(
            "/api/auth/login/verify", json={"challenge_id": challenge_id, "code": "abcdef"}
        )
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "invalid_code"

    # IP 잠금(같은 5회)은 따로 검사하므로 여기서는 풀고 challenge 폐기만 확인한다.
    device.app.state.login_limiter.clear()
    res = device.post(
        "/api/auth/login/verify",
        json={"challenge_id": challenge_id, "code": totp_now(secret, clock)},
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "challenge_expired"


def test_verify_requires_exactly_one_code(registered) -> None:
    device, _, codes = registered
    challenge_id = _challenge(device)
    for body in (
        {"challenge_id": challenge_id},
        {"challenge_id": challenge_id, "code": "123456", "recovery_code": codes[0]},
    ):
        res = device.post("/api/auth/login/verify", json=body)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "invalid_input"


@pytest.mark.parametrize(
    "body",
    [
        {"username": FAKE_USERNAME, "password": "wrong-password-123"},
        {"username": "nobody", "password": FAKE_PASSWORD},
    ],
)
def test_invalid_credentials_do_not_reveal_which(registered, body) -> None:
    device, _, _ = registered
    res = device.post("/api/auth/login", json=body)
    assert res.status_code == 401
    assert res.json() == {
        "error": {
            "code": "invalid_credentials",
            "message": "아이디 또는 비밀번호가 올바르지 않습니다.",
        }
    }


def test_login_before_setup(client: TestClient) -> None:
    res = client.post("/api/auth/login", json=LOGIN_BODY)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_credentials"


# ── 로그인 실패 제한 ──────────────────────────────────


def _assert_locked(res) -> int:
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "too_many_attempts"
    retry_after = int(res.headers["retry-after"])
    assert 0 < retry_after <= 15 * 60
    return retry_after


def test_five_password_failures_lock_for_15_minutes(registered, clock: FakeClock) -> None:
    device, secret, _ = registered
    bad = {"username": FAKE_USERNAME, "password": "wrong-password-123"}
    for _ in range(5):
        assert device.post("/api/auth/login", json=bad).status_code == 401

    # 맞는 비밀번호도 잠금 중에는 429
    assert _assert_locked(device.post("/api/auth/login", json=LOGIN_BODY)) == 15 * 60
    _assert_locked(
        device.post("/api/auth/login/verify", json={"challenge_id": "x", "code": "123456"})
    )

    clock.advance(15 * 60 - 1)
    assert _assert_locked(device.post("/api/auth/login", json=LOGIN_BODY)) == 1
    clock.advance(1)
    assert device.post("/api/auth/login", json=LOGIN_BODY).status_code == 200


def test_failures_across_password_and_code_are_combined(registered, clock: FakeClock) -> None:
    device, _, _ = registered
    bad = {"username": FAKE_USERNAME, "password": "wrong-password-123"}
    for _ in range(2):
        assert device.post("/api/auth/login", json=bad).status_code == 401
    challenge_id = _challenge(device)  # 비밀번호 성공은 횟수를 초기화하지 않는다
    for _ in range(3):
        res = device.post(
            "/api/auth/login/verify", json={"challenge_id": challenge_id, "recovery_code": "nope"}
        )
        assert res.status_code == 401
    _assert_locked(device.post("/api/auth/login", json=LOGIN_BODY))


def test_success_resets_failure_count(registered, clock: FakeClock) -> None:
    device, secret, _ = registered
    bad = {"username": FAKE_USERNAME, "password": "wrong-password-123"}
    for _ in range(4):
        assert device.post("/api/auth/login", json=bad).status_code == 401
    res = device.post(
        "/api/auth/login/verify",
        json={"challenge_id": _challenge(device), "code": totp_now(secret, clock)},
    )
    assert res.status_code == 204
    for _ in range(4):
        assert device.post("/api/auth/login", json=bad).status_code == 401
    assert device.post("/api/auth/login", json=LOGIN_BODY).status_code == 200


def test_old_failures_are_forgotten(registered, clock: FakeClock) -> None:
    device, _, _ = registered
    bad = {"username": FAKE_USERNAME, "password": "wrong-password-123"}
    for _ in range(4):
        assert device.post("/api/auth/login", json=bad).status_code == 401
    clock.advance(15 * 60)
    assert device.post("/api/auth/login", json=bad).status_code == 401
    assert device.post("/api/auth/login", json=LOGIN_BODY).status_code == 200


def test_lock_is_per_ip(registered) -> None:
    device, _, _ = registered
    bad = {"username": FAKE_USERNAME, "password": "wrong-password-123"}
    for _ in range(5):
        device.post("/api/auth/login", json=bad)
    _assert_locked(device.post("/api/auth/login", json=LOGIN_BODY))

    other_ip = TestClient(device.app, base_url="https://testserver", client=("198.51.100.7", 5000))
    assert other_ip.post("/api/auth/login", json=LOGIN_BODY).status_code == 200
