from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., TestClient]]:
    """환경변수를 지정한 뒤 앱을 새로 만들어 TestClient를 돌려준다."""
    # 개발자 셸의 값이 테스트에 섞이지 않게 비운다.
    for name in ("DB_PATH", "ENABLE_API_DOCS", "SESSION_SECRET", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    clients: list[TestClient] = []

    def _make(**env: str) -> TestClient:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        client = TestClient(create_app(), raise_server_exceptions=False)
        clients.append(client)
        return client

    yield _make

    for client in clients:
        client.close()
