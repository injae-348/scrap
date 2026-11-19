from pathlib import Path

import pytest

from app.config import DEFAULT_DB_PATH, load_settings

DOC_PATHS = [
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/docs",
    "/api/redoc",
    "/api/openapi.json",
]


@pytest.mark.parametrize("path", ["/api/nope", "/nope", "/", "/health"])
def test_unknown_path_404(make_client, tmp_path: Path, path: str) -> None:
    client = make_client(DB_PATH=str(tmp_path / "test.db"))

    res = client.get(path)

    assert res.status_code == 404
    assert res.json() == {
        "error": {"code": "not_found", "message": "요청한 항목을 찾을 수 없습니다."}
    }


@pytest.mark.parametrize("path", DOC_PATHS)
def test_api_docs_disabled_by_default(make_client, tmp_path: Path, path: str) -> None:
    client = make_client(DB_PATH=str(tmp_path / "test.db"))

    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", ["/api/docs", "/api/redoc", "/api/openapi.json"])
def test_api_docs_can_be_enabled(make_client, tmp_path: Path, path: str) -> None:
    client = make_client(DB_PATH=str(tmp_path / "test.db"), ENABLE_API_DOCS="1")

    assert client.get(path).status_code == 200


def test_default_db_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DB_PATH", raising=False)
    assert load_settings().db_path == DEFAULT_DB_PATH

    monkeypatch.setenv("DB_PATH", "   ")
    assert load_settings().db_path == DEFAULT_DB_PATH


def test_unexpected_error_returns_500_json(make_client, tmp_path: Path) -> None:
    client = make_client(DB_PATH=str(tmp_path / "test.db"))

    @client.app.get("/api/_boom")
    def boom() -> None:
        raise RuntimeError("내부 정보")

    res = client.get("/api/_boom")

    assert res.status_code == 500
    assert res.json() == {
        "error": {"code": "internal_error", "message": "서버 오류가 발생했습니다."}
    }
    assert "내부 정보" not in res.text


def test_validation_error_returns_400(make_client, tmp_path: Path) -> None:
    client = make_client(DB_PATH=str(tmp_path / "test.db"))

    @client.app.get("/api/_echo")
    def echo(n: int) -> dict[str, int]:
        return {"n": n}

    res = client.get("/api/_echo", params={"n": "abc"})

    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_input"
