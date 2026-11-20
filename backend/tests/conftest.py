import secrets
from collections.abc import Callable, Iterator

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.clock import Clock
from app.main import create_app

# 테스트 전용 가짜 값 (실제 비밀값 아님).
FAKE_SESSION_SECRET = "test-only-session-secret-0123456789abcdef"  # noqa: S105
# 가입 토큰은 저장소에 적힌 값(공개값)을 받지 않으므로, 실행할 때마다 무작위로 만든다.
FAKE_SETUP_TOKEN = secrets.token_hex(32)
FAKE_USERNAME = "tester"
FAKE_PASSWORD = "correct-horse-battery"  # noqa: S105
SITE_DOMAIN = "scrap.example.test"
SITE_ORIGIN = f"https://{SITE_DOMAIN}"

_ENV_NAMES = (
    "DB_PATH",
    "ENABLE_API_DOCS",
    "SESSION_SECRET",
    "ANTHROPIC_API_KEY",
    "SITE_DOMAIN",
    "ALLOWED_ORIGINS",
    "COOKIE_SECURE",
    "SETUP_TOKEN",
)


class FakeClock(Clock):
    """sleep 없이 시간을 앞당기는 시계."""

    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    # 개발자 셸의 값이 테스트에 섞이지 않게 비운다.
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def make_client(clean_env: pytest.MonkeyPatch) -> Iterator[Callable[..., TestClient]]:
    """환경변수를 지정한 뒤 앱을 새로 만들어 TestClient를 돌려준다.

    SESSION_SECRET·SETUP_TOKEN 은 가짜 값을 기본으로 넣는다 (덮어쓸 수 있음).
    SETUP_TOKEN 을 빼려면 `SETUP_TOKEN=""`을 넘긴다.
    https 로 요청해야 Secure 쿠키가 오간다.
    """
    clients: list[TestClient] = []

    def _make(clock: Clock | None = None, **env: str) -> TestClient:
        env.setdefault("SESSION_SECRET", FAKE_SESSION_SECRET)
        env.setdefault("SITE_DOMAIN", SITE_DOMAIN)
        env.setdefault("SETUP_TOKEN", FAKE_SETUP_TOKEN)
        for key, value in env.items():
            clean_env.setenv(key, value)
        client = TestClient(
            create_app(clock=clock), base_url="https://testserver", raise_server_exceptions=False
        )
        clients.append(client)
        return client

    yield _make

    for client in clients:
        client.close()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def client(make_client, clock: FakeClock, tmp_path) -> TestClient:
    return make_client(clock=clock, DB_PATH=str(tmp_path / "test.db"))


def totp_now(secret: str, clock: Clock) -> str:
    return pyotp.TOTP(secret).at(clock.now())


def do_setup(client: TestClient, clock: FakeClock) -> tuple[str, list[str]]:
    """가입을 끝내고 (TOTP 비밀값, 복구 코드)를 돌려준다. 끝나면 로그인 상태."""
    res = client.post(
        "/api/auth/setup",
        json={
            "username": FAKE_USERNAME,
            "password": FAKE_PASSWORD,
            "setup_token": FAKE_SETUP_TOKEN,
        },
    )
    assert res.status_code == 200, res.text
    secret = res.json()["secret"]
    res = client.post("/api/auth/setup/verify", json={"code": totp_now(secret, clock)})
    assert res.status_code == 200, res.text
    # 같은 구간 코드는 재사용할 수 없으므로 다음 구간으로 넘긴다.
    clock.advance(30)
    return secret, res.json()["recovery_codes"]


def do_login(client: TestClient, clock: FakeClock, secret: str) -> None:
    res = client.post(
        "/api/auth/login", json={"username": FAKE_USERNAME, "password": FAKE_PASSWORD}
    )
    assert res.status_code == 200, res.text
    res = client.post(
        "/api/auth/login/verify",
        json={"challenge_id": res.json()["challenge_id"], "code": totp_now(secret, clock)},
    )
    assert res.status_code == 204, res.text
    clock.advance(30)
