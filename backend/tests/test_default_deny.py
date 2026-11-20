"""인증 기본 거부: 공개 6개를 뺀 모든 /api/* 라우트는 세션 없이 401 `unauthorized`."""

import re

import pytest
from fastapi.testclient import TestClient

from app.routing import PUBLIC_ENDPOINTS, api_endpoints, assert_default_deny

# docs/API.md "인증 세부 규칙 (v1.1)"의 인증 불필요 경로 그대로.
EXPECTED_PUBLIC = {
    ("GET", "/api/health"),
    ("GET", "/api/auth/status"),
    ("POST", "/api/auth/setup"),
    ("POST", "/api/auth/setup/verify"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/login/verify"),
}


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def test_public_list_is_exactly_the_six_documented(client: TestClient) -> None:
    assert set(PUBLIC_ENDPOINTS) == EXPECTED_PUBLIC
    assert len(PUBLIC_ENDPOINTS) == 6
    registered_public = {
        (m, p) for m, p, _ in api_endpoints(client.app) if (m, p) in PUBLIC_ENDPOINTS
    }
    assert registered_public == EXPECTED_PUBLIC


def test_every_other_api_route_requires_session(client: TestClient) -> None:
    protected = [(m, p) for m, p, _ in api_endpoints(client.app) if (m, p) not in EXPECTED_PUBLIC]
    # 순회가 실제로 라우트를 찾았는지 (포함된 라우터까지 펼쳐졌는지) 확인
    assert ("GET", "/api/scraps") in protected
    assert ("POST", "/api/meta/preview") in protected
    assert ("DELETE", "/api/auth/sessions/{session_id}") in protected
    assert len(protected) >= 23

    for method, path in protected:
        url = _fill(path)
        for kwargs in ({}, {"json": {}}, {"json": {"url": "https://example.test", "ids": []}}):
            res = client.request(method, url, **kwargs)
            assert res.status_code == 401, (method, path, kwargs, res.text)
            assert res.json()["error"]["code"] == "unauthorized", (method, path)
            assert res.headers["cache-control"] == "no-store"


def test_forged_cookie_is_rejected_everywhere(client: TestClient) -> None:
    client.cookies.set("__Host-session", "forged-token")
    for method, path, _ in api_endpoints(client.app):
        if (method, path) in EXPECTED_PUBLIC:
            continue
        res = client.request(method, _fill(path))
        assert res.status_code == 401, (method, path)


def test_guard_rejects_unprotected_api_route(client: TestClient) -> None:
    app = client.app

    @app.get("/api/_open")
    def open_route() -> dict[str, str]:
        return {}

    with pytest.raises(RuntimeError, match="/api/_open"):
        assert_default_deny(app)


def test_guard_passes_for_real_app(client: TestClient) -> None:
    assert_default_deny(client.app)  # create_app 안에서도 실행된다


def test_docs_routes_allowed_only_as_docs(make_client, tmp_path) -> None:
    client = make_client(DB_PATH=str(tmp_path / "t.db"), ENABLE_API_DOCS="1", SITE_DOMAIN="")
    assert client.get("/api/openapi.json").status_code == 200
