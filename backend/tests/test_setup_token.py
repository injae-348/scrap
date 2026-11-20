"""가입 토큰 (SETUP_TOKEN, docs/API.md v1.2)."""

import logging
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import SESSION_SECRET_PLACEHOLDER, load_settings
from tests.conftest import (
    FAKE_PASSWORD,
    FAKE_SESSION_SECRET,
    FAKE_SETUP_TOKEN,
    FAKE_USERNAME,
    FakeClock,
    do_setup,
    totp_now,
)

BODY = {"username": FAKE_USERNAME, "password": FAKE_PASSWORD, "setup_token": FAKE_SETUP_TOKEN}


def _error_code(res) -> str:
    return res.json()["error"]["code"]


@pytest.mark.parametrize(
    "value",
    [
        "",  # 없음(빈 값)
        "   ",
        SESSION_SECRET_PLACEHOLDER,
        "x" * 31,  # 32자 미만
    ],
)
def test_setup_token_not_configured(make_client, clock: FakeClock, tmp_path: Path, value) -> None:
    client = make_client(clock=clock, DB_PATH=str(tmp_path / "t.db"), SETUP_TOKEN=value)
    # 앱은 정상 기동한다.
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/status").json()["setup_required"] is True

    # 토큰을 무엇으로 보내든 막힌다 (자리표시자를 그대로 보내도).
    for token in ("", value, SESSION_SECRET_PLACEHOLDER):
        res = client.post("/api/auth/setup", json={**BODY, "setup_token": token})
        assert res.status_code == 403
        assert _error_code(res) == "setup_token_not_configured"
    assert len(client.app.state.setup_pending) == 0


def test_setup_token_env_absent(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SESSION_SECRET", FAKE_SESSION_SECRET)
    assert load_settings().setup_token is None
    token = secrets.token_hex(16)  # 32자
    clean_env.setenv("SETUP_TOKEN", "  " + token + "  ")
    assert load_settings().setup_token == token


def test_setup_token_not_in_repr(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SESSION_SECRET", FAKE_SESSION_SECRET)
    clean_env.setenv("SETUP_TOKEN", FAKE_SETUP_TOKEN)
    assert FAKE_SETUP_TOKEN not in repr(load_settings())


@pytest.mark.parametrize(
    "body",
    [
        {**BODY, "setup_token": "wrong-token-" + "z" * 30},
        {**BODY, "setup_token": FAKE_SETUP_TOKEN[:-1]},
        {**BODY, "setup_token": ""},
        {"username": FAKE_USERNAME, "password": FAKE_PASSWORD},  # 누락
    ],
)
def test_invalid_or_missing_setup_token(client: TestClient, body) -> None:
    res = client.post("/api/auth/setup", json=body)
    assert res.status_code == 403
    assert _error_code(res) == "invalid_setup_token"
    assert len(client.app.state.setup_pending) == 0
    assert "set-cookie" not in res.headers


def test_matching_token_full_flow(client: TestClient, clock: FakeClock) -> None:
    res = client.post("/api/auth/setup", json=BODY)
    assert res.status_code == 200
    # /auth/setup/verify 는 토큰을 다시 받지 않는다.
    res = client.post(
        "/api/auth/setup/verify", json={"code": totp_now(res.json()["secret"], clock)}
    )
    assert res.status_code == 200
    assert len(res.json()["recovery_codes"]) == 10
    assert client.get("/api/auth/status").json() == {"setup_required": False, "logged_in": True}


def test_check_order(client: TestClient) -> None:
    # 토큰 불일치가 입력값 검사보다 먼저
    res = client.post(
        "/api/auth/setup", json={"username": "", "password": "short", "setup_token": "nope"}
    )
    assert res.status_code == 403
    assert _error_code(res) == "invalid_setup_token"
    # 토큰이 맞으면 입력값 검사
    res = client.post("/api/auth/setup", json={**BODY, "password": "short"})
    assert res.status_code == 400
    assert _error_code(res) == "invalid_input"
    res = client.post("/api/auth/setup", json={"setup_token": FAKE_SETUP_TOKEN})
    assert res.status_code == 400
    assert _error_code(res) == "invalid_input"


def test_not_configured_before_mismatch(make_client, tmp_path: Path) -> None:
    client = make_client(DB_PATH=str(tmp_path / "t.db"), SETUP_TOKEN="")
    res = client.post("/api/auth/setup", json={**BODY, "setup_token": "anything"})
    assert _error_code(res) == "setup_token_not_configured"


def test_wrong_token_five_times_locks(client: TestClient, clock: FakeClock) -> None:
    bad = {**BODY, "setup_token": "wrong-token-" + "z" * 30}
    for _ in range(5):
        assert client.post("/api/auth/setup", json=bad).status_code == 403

    # 맞는 토큰도 잠금 중에는 429, 로그인도 같은 잠금
    res = client.post("/api/auth/setup", json=BODY)
    assert res.status_code == 429
    assert _error_code(res) == "too_many_attempts"
    assert int(res.headers["retry-after"]) == 15 * 60
    res = client.post("/api/auth/login", json={"username": "a", "password": "b"})
    assert res.status_code == 429

    clock.advance(15 * 60)
    assert client.post("/api/auth/setup", json=BODY).status_code == 200


def test_setup_disabled_takes_priority(client: TestClient, clock: FakeClock) -> None:
    do_setup(client, clock)
    for token in (FAKE_SETUP_TOKEN, "wrong", ""):
        res = client.post("/api/auth/setup", json={**BODY, "setup_token": token})
        assert res.status_code == 403
        assert _error_code(res) == "setup_disabled"
    # 확정 후 setup 시도는 실패 횟수에 들어가지 않는다.
    assert client.app.state.login_limiter.retry_after("testclient") is None


def test_setup_disabled_before_not_configured(make_client, clock: FakeClock, tmp_path) -> None:
    db = str(tmp_path / "t.db")
    do_setup(make_client(clock=clock, DB_PATH=db), clock)
    client = make_client(clock=clock, DB_PATH=db, SETUP_TOKEN="")
    res = client.post("/api/auth/setup", json=BODY)
    assert _error_code(res) == "setup_disabled"


def test_startup_warns_when_token_left_after_setup(
    make_client, clock: FakeClock, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db = str(tmp_path / "t.db")
    do_setup(make_client(clock=clock, DB_PATH=db), clock)

    restarted = make_client(clock=clock, DB_PATH=db)
    with caplog.at_level(logging.WARNING, logger="app"), restarted:  # lifespan 실행
        pass
    assert "SETUP_TOKEN 을 지워도 됩니다" in caplog.text
    assert FAKE_SETUP_TOKEN not in caplog.text

    caplog.clear()
    removed = make_client(clock=clock, DB_PATH=db, SETUP_TOKEN="")
    with caplog.at_level(logging.WARNING, logger="app"), removed:
        pass
    assert "SETUP_TOKEN" not in caplog.text


def test_startup_warns_when_token_missing_before_setup(
    make_client, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    client = make_client(DB_PATH=str(tmp_path / "t.db"), SETUP_TOKEN=SESSION_SECRET_PLACEHOLDER)
    with caplog.at_level(logging.WARNING, logger="app"), client:
        pass
    assert "SETUP_TOKEN 이 설정되지 않았습니다" in caplog.text
    assert SESSION_SECRET_PLACEHOLDER not in caplog.text

    caplog.clear()
    configured = make_client(DB_PATH=str(tmp_path / "t.db"))
    with caplog.at_level(logging.WARNING, logger="app"), configured:
        pass
    assert "SETUP_TOKEN" not in caplog.text
    assert FAKE_SETUP_TOKEN not in caplog.text
