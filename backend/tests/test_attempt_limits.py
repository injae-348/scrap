"""시도 제한: 동시 요청 예약과 계정 단위 2단계 실패 상한."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.auth.router as auth_router
from app.db import Database
from app.ratelimit import AccountAttemptLimiter, AttemptRejected, LoginAttemptLimiter
from tests.conftest import FAKE_PASSWORD, FAKE_USERNAME, FakeClock, do_setup, totp_now

LOGIN_BODY = {"username": FAKE_USERNAME, "password": FAKE_PASSWORD}
# 동시 요청이 실제로 겹치도록 검증 함수를 잠깐 붙잡아 둔다 (시간 판정에는 쓰지 않는다).
HOLD_SECONDS = 0.2


def _device(client: TestClient, ip: str = "testclient") -> TestClient:
    return TestClient(client.app, base_url="https://testserver", client=(ip, 50000))


def _challenge(device: TestClient) -> str:
    res = device.post("/api/auth/login", json=LOGIN_BODY)
    assert res.status_code == 200, res.text
    return res.json()["challenge_id"]


class _SlowFalse:
    """호출 횟수를 세고, 잠깐 기다렸다가 실패(False)를 돌려주는 대역."""

    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self, *args, **kwargs) -> bool:
        with self._lock:
            self.calls += 1
        time.sleep(HOLD_SECONDS)
        return False


def _fire(n: int, fn) -> list[int]:
    with ThreadPoolExecutor(max_workers=n) as pool:
        return [f.result() for f in [pool.submit(fn, i) for i in range(n)]]


# ── 단위: 예약 ──────────────────────────────────────


def test_reservation_counts_in_flight(clock: FakeClock) -> None:
    limiter = LoginAttemptLimiter(clock)
    for _ in range(5):
        limiter.begin("ip")
    with pytest.raises(AttemptRejected) as excinfo:
        limiter.begin("ip")
    assert excinfo.value.retry_after == 1
    # 성공으로 끝나면 자리가 난다.
    limiter.finish("ip", failed=False)
    limiter.begin("ip")
    # 실패 5회가 기록되면 15분 잠금
    for _ in range(5):
        limiter.finish("ip", failed=True)
    with pytest.raises(AttemptRejected) as excinfo:
        limiter.begin("ip")
    assert excinfo.value.retry_after == 15 * 60


@pytest.fixture
def database(clock: FakeClock, tmp_path: Path) -> Database:
    """사용자 1명(id 1)이 있는 DB."""
    db = Database(str(tmp_path / "limits.db"), clock.now)
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, totp_secret, created_at)"
            " VALUES (1, 'tester', 'x', 'x', 'x')"
        )
    finally:
        conn.close()
    return db


def test_account_limiter_window(clock: FakeClock, database: Database) -> None:
    limiter = AccountAttemptLimiter(clock, database.connect)
    for _ in range(9):
        limiter.record_failure("1")
    clock.advance(15 * 60)  # 15분 창 밖으로 밀려난다
    for _ in range(9):
        limiter.record_failure("1")
    assert limiter.retry_after("1") is None
    limiter.record_failure("1")
    assert limiter.retry_after("1") == 15 * 60


# ── 동시 요청 ──────────────────────────────────────


def test_concurrent_wrong_codes_same_ip_evaluated_at_most_5(
    client: TestClient, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    do_setup(client, clock)
    device = _device(client)
    challenge_id = _challenge(device)
    slow = _SlowFalse()
    monkeypatch.setattr(auth_router, "_consume_totp", slow)

    statuses = _fire(
        20,
        lambda _: (
            device.post(
                "/api/auth/login/verify", json={"challenge_id": challenge_id, "code": "123456"}
            ).status_code
        ),
    )

    assert slow.calls <= 5
    assert statuses.count(401) == slow.calls
    assert set(statuses) <= {401, 429}
    # 실패가 쌓였으면 잠금
    if slow.calls == 5:
        assert device.post("/api/auth/login", json=LOGIN_BODY).status_code == 429


def test_concurrent_wrong_codes_many_ips_same_challenge_at_most_5(
    client: TestClient, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # IP별 제한을 피해 여러 IP로 보내도 challenge 하나에서는 5번까지만 평가된다.
    do_setup(client, clock)
    challenge_id = _challenge(_device(client))
    slow = _SlowFalse()
    monkeypatch.setattr(auth_router, "_consume_totp", slow)

    statuses = _fire(
        20,
        lambda i: (
            _device(client, f"198.51.100.{i + 1}")
            .post("/api/auth/login/verify", json={"challenge_id": challenge_id, "code": "123456"})
            .status_code
        ),
    )

    assert 1 <= slow.calls <= 5
    # 400: challenge 자리 없음, 429: 계정 단위 자리(10개) 없음
    assert set(statuses) <= {400, 401, 429}
    assert statuses.count(401) == slow.calls


def test_concurrent_password_guesses_at_most_5(
    client: TestClient, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    do_setup(client, clock)
    device = _device(client)
    slow = _SlowFalse()
    monkeypatch.setattr(auth_router, "verify_password", slow)

    statuses = _fire(
        20,
        lambda _: (
            device.post(
                "/api/auth/login", json={"username": FAKE_USERNAME, "password": "guess-password-x"}
            ).status_code
        ),
    )

    assert 1 <= slow.calls <= 5
    assert statuses.count(401) == slow.calls
    assert set(statuses) <= {401, 429}


# ── 계정 단위 2단계 실패 상한 ─────────────────────────


def _wrong_codes(device: TestClient, n: int) -> None:
    challenge_id = _challenge(device)
    for _ in range(n):
        res = device.post(
            "/api/auth/login/verify", json={"challenge_id": challenge_id, "code": "abcdef"}
        )
        assert res.status_code == 401


def test_account_lock_after_10_code_failures_across_ips(
    client: TestClient, clock: FakeClock
) -> None:
    secret, codes = do_setup(client, clock)
    # IP마다 4번씩(IP 잠금 5번 미만) → 합계 10번
    _wrong_codes(_device(client, "198.51.100.1"), 4)
    _wrong_codes(_device(client, "198.51.100.2"), 4)
    _wrong_codes(_device(client, "198.51.100.3"), 2)

    fresh = _device(client, "203.0.113.9")
    challenge_id = _challenge(fresh)  # 비밀번호 단계는 막지 않는다
    res = fresh.post(
        "/api/auth/login/verify",
        json={"challenge_id": challenge_id, "code": totp_now(secret, clock)},
    )
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "too_many_attempts"
    assert int(res.headers["retry-after"]) == 15 * 60
    res = fresh.post(
        "/api/auth/login/verify", json={"challenge_id": challenge_id, "recovery_code": codes[0]}
    )
    assert res.status_code == 429

    # 이미 로그인된 기기는 그대로 쓸 수 있다.
    assert client.get("/api/auth/sessions").status_code == 200

    clock.advance(15 * 60)
    res = fresh.post(
        "/api/auth/login/verify",
        json={"challenge_id": _challenge(fresh), "code": totp_now(secret, clock)},
    )
    assert res.status_code == 204


def test_account_failures_outside_window_do_not_lock(client: TestClient, clock: FakeClock) -> None:
    secret, _ = do_setup(client, clock)
    _wrong_codes(_device(client, "198.51.100.1"), 4)
    _wrong_codes(_device(client, "198.51.100.2"), 4)
    clock.advance(15 * 60)
    _wrong_codes(_device(client, "198.51.100.3"), 4)

    fresh = _device(client, "203.0.113.9")
    res = fresh.post(
        "/api/auth/login/verify",
        json={"challenge_id": _challenge(fresh), "code": totp_now(secret, clock)},
    )
    assert res.status_code == 204


def test_account_lock_logs_count_only(
    client: TestClient, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    do_setup(client, clock)
    with caplog.at_level("WARNING", logger="app"):
        _wrong_codes(_device(client, "198.51.100.1"), 4)
        _wrong_codes(_device(client, "198.51.100.2"), 4)
        _wrong_codes(_device(client, "198.51.100.3"), 2)
    assert "2단계 인증 실패" in caplog.text
    assert "198.51.100" not in caplog.text


def test_account_limiter_state_survives_new_instance(clock: FakeClock, database: Database) -> None:
    first = AccountAttemptLimiter(clock, database.connect)
    for _ in range(10):
        first.record_failure("1")
    assert first.retry_after("1") == 15 * 60

    clock.advance(60)
    second = AccountAttemptLimiter(clock, database.connect)
    assert second.retry_after("1") == 14 * 60
    with pytest.raises(AttemptRejected):
        second.begin("1")

    # 잠금이 끝나면 잠금 전 실패는 세지 않고 새로 센다.
    clock.advance(14 * 60)
    for _ in range(9):
        second.record_failure("1")
    assert second.retry_after("1") is None
    second.record_failure("1")
    assert second.retry_after("1") == 15 * 60


def test_account_limiter_prunes_old_rows(clock: FakeClock, database: Database) -> None:
    limiter = AccountAttemptLimiter(clock, database.connect)
    for _ in range(5):
        limiter.record_failure("1")
    clock.advance(15 * 60)
    limiter.record_failure("1")
    conn = database.connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM login_code_failures").fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_account_lock_survives_restart(make_client, clock: FakeClock, tmp_path: Path) -> None:
    db_path = str(tmp_path / "restart.db")
    first = make_client(clock=clock, DB_PATH=db_path)
    secret, _ = do_setup(first, clock)
    _wrong_codes(_device(first, "198.51.100.1"), 4)
    _wrong_codes(_device(first, "198.51.100.2"), 4)
    _wrong_codes(_device(first, "198.51.100.3"), 2)

    # 같은 DB로 앱을 새로 만든다 (프로세스 재시작과 같음). IP별 제한은 새로 시작한다.
    clock.advance(60)
    restarted = make_client(clock=clock, DB_PATH=db_path)
    fresh = _device(restarted, "203.0.113.9")
    res = fresh.post(
        "/api/auth/login/verify",
        json={"challenge_id": _challenge(fresh), "code": totp_now(secret, clock)},
    )
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "too_many_attempts"
    assert int(res.headers["retry-after"]) == 14 * 60

    clock.advance(14 * 60)
    res = fresh.post(
        "/api/auth/login/verify",
        json={"challenge_id": _challenge(fresh), "code": totp_now(secret, clock)},
    )
    assert res.status_code == 204


def test_account_failures_counted_across_restart(
    make_client, clock: FakeClock, tmp_path: Path
) -> None:
    # 잠금 전 실패 기록도 재시작 뒤에 이어서 센다.
    db_path = str(tmp_path / "restart.db")
    first = make_client(clock=clock, DB_PATH=db_path)
    do_setup(first, clock)
    _wrong_codes(_device(first, "198.51.100.1"), 4)
    _wrong_codes(_device(first, "198.51.100.2"), 4)

    restarted = make_client(clock=clock, DB_PATH=db_path)
    _wrong_codes(_device(restarted, "198.51.100.3"), 2)
    assert restarted.app.state.account_limiter.retry_after("1") == 15 * 60


def test_account_failures_outside_window_ignored_after_restart(
    make_client, clock: FakeClock, tmp_path: Path
) -> None:
    db_path = str(tmp_path / "restart.db")
    first = make_client(clock=clock, DB_PATH=db_path)
    secret, _ = do_setup(first, clock)
    _wrong_codes(_device(first, "198.51.100.1"), 4)
    _wrong_codes(_device(first, "198.51.100.2"), 4)

    clock.advance(15 * 60)  # 위의 8회는 창 밖
    restarted = make_client(clock=clock, DB_PATH=db_path)
    _wrong_codes(_device(restarted, "198.51.100.3"), 4)
    assert restarted.app.state.account_limiter.retry_after("1") is None

    fresh = _device(restarted, "203.0.113.9")
    res = fresh.post(
        "/api/auth/login/verify",
        json={"challenge_id": _challenge(fresh), "code": totp_now(secret, clock)},
    )
    assert res.status_code == 204


def test_account_failures_kept_after_successful_login(client: TestClient, clock: FakeClock) -> None:
    # 2단계 성공은 IP별 연속 실패만 초기화한다. 계정 단위 실패는 창이 지나야 빠진다.
    secret, _ = do_setup(client, clock)
    _wrong_codes(_device(client, "198.51.100.1"), 4)
    _wrong_codes(_device(client, "198.51.100.2"), 4)
    _wrong_codes(_device(client, "198.51.100.3"), 1)

    ok = _device(client, "203.0.113.9")
    res = ok.post(
        "/api/auth/login/verify",
        json={"challenge_id": _challenge(ok), "code": totp_now(secret, clock)},
    )
    assert res.status_code == 204
    clock.advance(30)

    _wrong_codes(_device(client, "198.51.100.4"), 1)  # 합계 10회
    fresh = _device(client, "203.0.113.10")
    res = fresh.post(
        "/api/auth/login/verify",
        json={"challenge_id": _challenge(fresh), "code": totp_now(secret, clock)},
    )
    assert res.status_code == 429
