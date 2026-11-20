"""인증 보강: IP 키 정규화, 재설정 후 세션 정리, 비밀값 repr, 비정상 입력,
no-store, Argon2 대기 상한, 가입 대기 틀린 코드 제한."""

import logging
import re
import secrets

import pytest
from fastapi.testclient import TestClient

import app.auth.crypto as crypto
from app.auth.crypto import TokenHasher, match_totp
from app.auth.router import PendingSetup, PendingTotpReset
from app.config import PUBLIC_SETUP_TOKEN_VALUES, load_settings
from app.ratelimit import client_key
from tests.conftest import (
    FAKE_PASSWORD,
    FAKE_SESSION_SECRET,
    FAKE_SETUP_TOKEN,
    FAKE_USERNAME,
    FakeClock,
    do_login,
    do_setup,
    totp_now,
)

SETUP_BODY = {"username": FAKE_USERNAME, "password": FAKE_PASSWORD, "setup_token": FAKE_SETUP_TOKEN}
UNICODE_DIGITS = "١٢٣٤٥٦"  # 아라비아-인도 숫자 6개 (str.isdigit() 참)


def _device(client: TestClient, ip: str = "testclient", ua: str | None = None) -> TestClient:
    headers = {"User-Agent": ua} if ua is not None else None
    return TestClient(
        client.app, base_url="https://testserver", client=(ip, 50000), headers=headers
    )


# ── IP 키 정규화 ────────────────────────────────


@pytest.mark.parametrize(
    ("host", "key"),
    [
        ("192.0.2.10", "192.0.2.10"),
        ("::ffff:192.0.2.10", "192.0.2.10"),
        ("2001:db8:1:2:3:4:5:6", "2001:db8:1:2::/64"),
        ("2001:db8:1:2:ffff::1", "2001:db8:1:2::/64"),
        ("2001:db8:1:3::1", "2001:db8:1:3::/64"),
        ("fe80::1%eth0", "fe80::/64"),
        ("testclient", "testclient"),
        (None, "unknown"),
        ("", "unknown"),
    ],
)
def test_client_key(host, key) -> None:
    assert client_key(host) == key


def test_ipv6_same_64_shares_limits(client: TestClient, clock: FakeClock) -> None:
    do_setup(client, clock)
    bad = {"username": FAKE_USERNAME, "password": "wrong-password-123"}
    for i in range(5):
        res = _device(client, f"2001:db8:1:2::{i + 1}").post("/api/auth/login", json=bad)
        assert res.status_code == 401
    # 같은 /64의 다른 주소도 잠긴다.
    assert _device(client, "2001:db8:1:2::99").post("/api/auth/login", json=bad).status_code == 429
    # 다른 /64는 따로 센다.
    assert _device(client, "2001:db8:1:3::1").post("/api/auth/login", json=bad).status_code == 401


def test_ipv4_mapped_counts_as_ipv4(client: TestClient) -> None:
    client.app.state.request_limiter.limit = 2
    _device(client, "192.0.2.7").get("/api/health")
    _device(client, "::ffff:192.0.2.7").get("/api/health")
    assert _device(client, "192.0.2.7").get("/api/health").status_code == 429


def test_private_client_ip_warning_once_in_production(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    # conftest 기본값에 SITE_DOMAIN이 있어 운영으로 본다.
    with caplog.at_level(logging.WARNING, logger="app"):
        _device(client, "172.30.80.10").get("/api/health")
        _device(client, "172.30.80.10").get("/api/health")
        _device(client, "127.0.0.1").get("/api/health")
    assert caplog.text.count("사설 주소") == 1
    assert "172.30.80.10" not in caplog.text


# ── TOTP 재설정 확정 시 다른 세션 로그아웃 ───────────


def test_totp_reset_logs_out_other_sessions(client: TestClient, clock: FakeClock) -> None:
    secret, _ = do_setup(client, clock)
    phone = _device(client, ua="FakePhone/1.0")
    do_login(phone, clock, secret)
    assert len(client.get("/api/auth/sessions").json()) == 2

    res = client.post(
        "/api/auth/totp/reset", json={"password": FAKE_PASSWORD, "code": totp_now(secret, clock)}
    )
    new_secret = res.json()["secret"]
    clock.advance(30)
    # 확정 전에는 다른 기기도 유지
    assert phone.get("/api/auth/sessions").status_code == 200

    res = client.post("/api/auth/totp/reset/verify", json={"code": totp_now(new_secret, clock)})
    assert res.status_code == 200

    assert phone.get("/api/auth/sessions").status_code == 401
    sessions = client.get("/api/auth/sessions").json()
    assert len(sessions) == 1
    assert sessions[0]["current"] is True


# ── SETUP_TOKEN 값 품질 ─────────────────────────


@pytest.mark.parametrize("value", sorted(PUBLIC_SETUP_TOKEN_VALUES))
def test_public_setup_token_values_rejected(make_client, tmp_path, value: str) -> None:
    client = make_client(DB_PATH=str(tmp_path / "t.db"), SETUP_TOKEN=value)
    res = client.post("/api/auth/setup", json={**SETUP_BODY, "setup_token": value})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "setup_token_not_configured"


def test_low_entropy_setup_token_rejected(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SESSION_SECRET", FAKE_SESSION_SECRET)
    clean_env.setenv("SETUP_TOKEN", "ab" * 20)  # 40자지만 글자 종류 2개
    assert load_settings().setup_token is None
    clean_env.setenv("SETUP_TOKEN", "0123456789" * 4)  # 글자 종류 10개
    assert load_settings().setup_token == "0123456789" * 4


def test_setup_token_equal_to_session_secret_rejected(
    clean_env: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = secrets.token_hex(32)
    clean_env.setenv("SESSION_SECRET", secret)
    clean_env.setenv("SETUP_TOKEN", secret)
    with caplog.at_level(logging.WARNING, logger="app"):
        assert load_settings().setup_token is None
    assert "SESSION_SECRET 과 같아" in caplog.text
    assert secret not in caplog.text


def test_readme_example_is_generated() -> None:
    # README 예시는 고정값이 아니라 생성 명령이어야 한다.
    from pathlib import Path

    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    line = next(ln for ln in readme.splitlines() if "SETUP_TOKEN=" in ln and "export" in ln)
    assert "$(openssl rand -hex 32)" in line


# ── Argon2 대기 상한, 가짜 해시 미리 계산 ──────────────


def test_password_hasher_busy_returns_429(
    client: TestClient, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    do_setup(client, clock)
    import threading

    monkeypatch.setattr(crypto, "_hash_slots", threading.BoundedSemaphore(1))
    monkeypatch.setattr(crypto, "HASH_WAIT_SECONDS", 0.01)
    crypto._hash_slots.acquire()  # 자리를 모두 차지한 상태
    try:
        res = client.post(
            "/api/auth/login", json={"username": FAKE_USERNAME, "password": FAKE_PASSWORD}
        )
    finally:
        crypto._hash_slots.release()
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "too_many_requests"
    assert res.headers["retry-after"] == "1"
    # 실패 횟수에 들어가지 않는다.
    assert client.app.state.login_limiter._state("testclient", clock.now())[0] == 0


def test_dummy_hash_prepared_at_startup(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(crypto, "_dummy_hash", None)
    with client:  # lifespan 실행
        assert crypto._dummy_hash is not None


# ── 비밀값 repr ────────────────────────────────


def test_secrets_not_in_repr() -> None:
    hasher = TokenHasher.from_secret(FAKE_SESSION_SECRET)
    assert hasher.session_key.hex() not in repr(hasher)
    assert repr(hasher.session_key) not in repr(hasher)

    fake_secret = crypto.new_totp_secret()
    fake_hash = "$argon2id$fake-hash-for-repr-test"
    pending = PendingSetup(username="u", password_hash=fake_hash, totp_secret=fake_secret)
    assert fake_hash not in repr(pending)
    assert fake_secret not in repr(pending)
    reset = PendingTotpReset(user_id=1, totp_secret=fake_secret)
    assert fake_secret not in repr(reset)


# ── 비정상 입력이 500이 되지 않는다 ──────────────────


def test_unicode_digit_totp_not_500(client: TestClient, clock: FakeClock) -> None:
    assert match_totp("JBSWY3DPEHPK3PXP", UNICODE_DIGITS, 0, None) is None

    # 가입 확정
    client.post("/api/auth/setup", json=SETUP_BODY)
    res = client.post("/api/auth/setup/verify", json={"code": UNICODE_DIGITS})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_code"


def test_unicode_digit_login_and_reset_not_500(client: TestClient, clock: FakeClock) -> None:
    do_setup(client, clock)
    device = _device(client)
    res = device.post(
        "/api/auth/login", json={"username": FAKE_USERNAME, "password": FAKE_PASSWORD}
    )
    res = device.post(
        "/api/auth/login/verify",
        json={"challenge_id": res.json()["challenge_id"], "code": UNICODE_DIGITS},
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_code"

    res = client.post(
        "/api/auth/totp/reset", json={"password": FAKE_PASSWORD, "code": UNICODE_DIGITS}
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_code"


@pytest.mark.parametrize("session_id", [str(2**63), str(2**70), "0", "-1"])
def test_out_of_range_session_id_404(client: TestClient, clock: FakeClock, session_id: str) -> None:
    do_setup(client, clock)
    res = client.delete(f"/api/auth/sessions/{session_id}")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


# ── no-store ─────────────────────────────────


def test_api_responses_have_no_store(client: TestClient, clock: FakeClock) -> None:
    responses = [
        client.get("/api/health"),
        client.get("/api/auth/status"),
        client.get("/api/nope"),  # 404
        client.post("/api/auth/setup", json=SETUP_BODY, headers={"Origin": "https://evil.test"}),
        client.post("/api/auth/setup", json=SETUP_BODY),
    ]
    secret = responses[-1].json()["secret"]
    responses.append(client.post("/api/auth/setup/verify", json={"code": totp_now(secret, clock)}))
    responses.append(client.get("/api/auth/sessions"))
    client.app.state.request_limiter.limit = 0
    responses.append(client.get("/api/health"))  # 429 (미들웨어)

    assert [r.status_code for r in responses] == [200, 200, 404, 403, 200, 200, 200, 429]
    for res in responses:
        assert res.headers["cache-control"] == "no-store"


def test_non_api_paths_untouched(client: TestClient) -> None:
    assert "cache-control" not in client.get("/nope").headers


# ── 가입 대기의 틀린 코드 5회 → 폐기 ────────────────


def test_setup_pending_discarded_after_5_wrong_codes(client: TestClient, clock: FakeClock) -> None:
    secret = client.post("/api/auth/setup", json=SETUP_BODY).json()["secret"]
    for _ in range(5):
        res = client.post("/api/auth/setup/verify", json={"code": "abcdef"})
        assert res.status_code == 401
    res = client.post("/api/auth/setup/verify", json={"code": totp_now(secret, clock)})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "setup_expired"


def test_setup_wrong_codes_below_limit_keep_pending(client: TestClient, clock: FakeClock) -> None:
    secret = client.post("/api/auth/setup", json=SETUP_BODY).json()["secret"]
    for _ in range(4):
        assert client.post("/api/auth/setup/verify", json={"code": "abcdef"}).status_code == 401
    res = client.post("/api/auth/setup/verify", json={"code": totp_now(secret, clock)})
    assert res.status_code == 200


# ── 비정상 본문 ──────────────────────────────────────


@pytest.mark.parametrize(
    "kwargs",
    [
        {"content": "{", "headers": {"content-type": "application/json"}},
        {"json": {**SETUP_BODY, "setup_token": 123}},
        {"json": {**SETUP_BODY, "username": ["a"]}},
        {"json": {**SETUP_BODY, "password": None}},
        {"json": ["not", "an", "object"]},
    ],
)
def test_malformed_setup_body_400_before_token_check(client: TestClient, kwargs) -> None:
    res = client.post("/api/auth/setup", **kwargs)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_input"
    # 토큰 검사에 이르지 않았으니 실패 횟수도 없다.
    assert client.app.state.login_limiter._state("testclient", 0)[0] == 0


def test_recovery_code_format(client: TestClient, clock: FakeClock) -> None:
    _, codes = do_setup(client, clock)
    assert len(codes) == 10
    for code in codes:
        assert re.fullmatch(r"([A-HJ-NP-Z2-9]{4}-){3}[A-HJ-NP-Z2-9]{4}", code), code


def test_username_is_stripped_and_control_chars_rejected(
    client: TestClient, clock: FakeClock
) -> None:
    for bad in ("te\x00ster", "tes\nter", "te\x7fster"):
        res = client.post("/api/auth/setup", json={**SETUP_BODY, "username": bad})
        assert res.status_code == 400, repr(bad)
        assert res.json()["error"]["code"] == "invalid_input"

    res = client.post("/api/auth/setup", json={**SETUP_BODY, "username": "  spaced user  "})
    assert res.status_code == 200
    res = client.post(
        "/api/auth/setup/verify", json={"code": totp_now(res.json()["secret"], clock)}
    )
    assert res.status_code == 200
    conn = client.app.state.db.connect()
    try:
        assert conn.execute("SELECT username FROM users").fetchone()[0] == "spaced user"
    finally:
        conn.close()


def test_password_length_limits(client: TestClient) -> None:
    res = client.post("/api/auth/setup", json={**SETUP_BODY, "password": "a" * 1025})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_input"
    res = client.post("/api/auth/setup", json={**SETUP_BODY, "password": "a" * 1024})
    assert res.status_code == 200


def test_login_username_surrounding_spaces(client: TestClient, clock: FakeClock) -> None:
    do_setup(client, clock)
    res = _device(client).post(
        "/api/auth/login", json={"username": f"  {FAKE_USERNAME} ", "password": FAKE_PASSWORD}
    )
    assert res.status_code == 200


def test_sessions_sorted_by_last_seen_desc(client: TestClient, clock: FakeClock) -> None:
    secret, _ = do_setup(client, clock)  # 기기 A
    phone = _device(client, ua="FakePhone/1.0")
    do_login(phone, clock, secret)  # 기기 B

    # 요청을 보낸 기기는 목록을 만들기 전에 last_seen_at이 갱신된다 (1시간 간격).
    clock.advance(2 * 60 * 60)
    sessions = phone.get("/api/auth/sessions").json()
    assert [s["user_agent"] for s in sessions][0] == "FakePhone/1.0"
    assert sessions[0]["last_seen_at"] > sessions[1]["last_seen_at"]

    clock.advance(2 * 60 * 60)
    sessions = client.get("/api/auth/sessions").json()
    assert [s["current"] for s in sessions] == [True, False]
    assert sessions[0]["last_seen_at"] > sessions[1]["last_seen_at"]


def test_user_agent_truncated_and_optional(client: TestClient, clock: FakeClock) -> None:
    secret, _ = do_setup(client, clock)
    long_ua = _device(client, ua="X" * 2000)
    do_login(long_ua, clock, secret)
    agents = [s["user_agent"] for s in client.get("/api/auth/sessions").json()]
    assert "X" * 512 in agents
    assert all(len(a) <= 512 for a in agents)


def test_status_logged_out_after_180_days(client: TestClient, clock: FakeClock) -> None:
    do_setup(client, clock)
    clock.advance(180 * 24 * 60 * 60)
    assert client.get("/api/auth/status").json() == {"setup_required": False, "logged_in": False}
