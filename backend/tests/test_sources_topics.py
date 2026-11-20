"""출처·주제 API와 출처 자동 판별 (docs/API.md v1.3)."""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeClock

DEFAULT_SOURCES = [
    ("유튜브", ["youtube.com", "youtu.be"], False),
    ("X", ["x.com", "twitter.com"], False),
    ("일반사이트", [], True),
    ("당근", ["daangn.com"], False),
    ("커뮤니티", [], False),
]


def _sources(client: TestClient) -> list[dict]:
    res = client.get("/api/sources")
    assert res.status_code == 200
    return res.json()


def _source_id(client: TestClient, name: str) -> int:
    return next(s["id"] for s in _sources(client) if s["name"] == name)


def _detect(client: TestClient, url: str) -> int:
    res = client.post("/api/scraps", json={"url": url})
    assert res.status_code == 201, res.text
    return res.json()["source"]["id"]


# ── 출처 ────────────────────────────────────────────


def test_default_sources_seeded(user: TestClient) -> None:
    sources = _sources(user)
    assert [(s["name"], s["domain_patterns"], s["is_default"]) for s in sources] == DEFAULT_SOURCES
    for s in sources:
        assert set(s) == {"id", "name", "domain_patterns", "is_default"}


def test_topics_start_empty(user: TestClient) -> None:
    assert user.get("/api/topics").json() == []


def test_create_source_normalizes_patterns(user: TestClient) -> None:
    res = user.post(
        "/api/sources",
        json={"name": "  블로그 ", "domain_patterns": [" Blog.Example.TEST ", "blog.example.test"]},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "블로그"
    assert body["domain_patterns"] == ["blog.example.test"]
    assert body["is_default"] is False
    assert _sources(user)[-1]["id"] == body["id"]  # 맨 뒤 순서


def test_create_source_without_patterns(user: TestClient) -> None:
    res = user.post("/api/sources", json={"name": "뉴스"})
    assert res.status_code == 201
    assert res.json()["domain_patterns"] == []


@pytest.mark.parametrize(
    "pattern",
    [
        "https://a.example.test",
        "a.example.test/path",
        "a.example.test:8080",
        "",
        "   ",
        "a..example.test",
        ".example.test",
        "example.test.",
        "예시.test",
        "a_b.test",
        "x" * 254,
    ],
)
def test_invalid_patterns_rejected(user: TestClient, pattern: str) -> None:
    res = user.post("/api/sources", json={"name": "새 출처", "domain_patterns": [pattern]})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_input"


def test_pattern_count_limit(user: TestClient) -> None:
    patterns = [f"s{i}.example.test" for i in range(21)]
    res = user.post("/api/sources", json={"name": "많음", "domain_patterns": patterns})
    assert res.status_code == 400
    ok = user.post("/api/sources", json={"name": "많음", "domain_patterns": patterns[:20]})
    assert ok.status_code == 201


def test_pattern_used_by_other_source(user: TestClient) -> None:
    res = user.post("/api/sources", json={"name": "다른", "domain_patterns": ["YouTube.com"]})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "duplicate_pattern"
    # 자기 자신이 이미 가진 패턴으로 바꾸는 것은 괜찮다
    yt = _source_id(user, "유튜브")
    res = user.patch(f"/api/sources/{yt}", json={"domain_patterns": ["youtu.be", "youtube.com"]})
    assert res.status_code == 200
    assert res.json()["domain_patterns"] == ["youtu.be", "youtube.com"]


@pytest.mark.parametrize("name", ["x", " X ", "유튜브"])
def test_duplicate_source_name_case_insensitive(user: TestClient, name: str) -> None:
    res = user.post("/api/sources", json={"name": name})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "duplicate_name"


@pytest.mark.parametrize("name", ["", "   ", "가" * 31, "a\nb"])
def test_invalid_source_name(user: TestClient, name: str) -> None:
    res = user.post("/api/sources", json={"name": name})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_input"


def test_source_name_30_chars_ok(user: TestClient) -> None:
    assert user.post("/api/sources", json={"name": "가" * 30}).status_code == 201


@pytest.mark.parametrize(
    "body",
    [
        {"name": "새", "is_default": True},
        {"name": "새", "id": 9},
        {"name": 1},
        {"name": "새", "domain_patterns": "a.test"},
        {"domain_patterns": []},
    ],
)
def test_source_body_rules(user: TestClient, body: dict) -> None:
    res = user.post("/api/sources", json=body)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_input"


def test_update_source(user: TestClient) -> None:
    sid = _source_id(user, "커뮤니티")
    res = user.patch(
        f"/api/sources/{sid}", json={"name": "커뮤니티2", "domain_patterns": ["c.test"]}
    )
    assert res.status_code == 200
    assert res.json() == {
        "id": sid,
        "name": "커뮤니티2",
        "domain_patterns": ["c.test"],
        "is_default": False,
    }
    # 대소문자만 바꾸는 이름 변경은 자기 자신과 중복이 아니다
    x = _source_id(user, "X")
    assert user.patch(f"/api/sources/{x}", json={"name": "x"}).json()["name"] == "x"
    # 다른 출처와 같은 이름
    res = user.patch(f"/api/sources/{sid}", json={"name": "유튜브"})
    assert res.json()["error"]["code"] == "duplicate_name"
    # null·is_default 변경 불가
    assert user.patch(f"/api/sources/{sid}", json={"name": None}).status_code == 400
    assert user.patch(f"/api/sources/{sid}", json={"domain_patterns": None}).status_code == 400
    assert user.patch(f"/api/sources/{sid}", json={"is_default": True}).status_code == 400


def test_default_source_patterns_always_empty(user: TestClient) -> None:
    default = _source_id(user, "일반사이트")
    res = user.patch(f"/api/sources/{default}", json={"domain_patterns": ["g.test"]})
    assert res.status_code == 400
    assert user.patch(f"/api/sources/{default}", json={"domain_patterns": []}).status_code == 200
    res = user.patch(f"/api/sources/{default}", json={"name": "기타"})
    assert res.status_code == 200
    assert res.json()["is_default"] is True


def test_update_missing_source(user: TestClient) -> None:
    for sid in (999, 0, -1, 2**70):
        res = user.patch(f"/api/sources/{sid}", json={"name": "a"})
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"


def test_delete_default_source_forbidden(user: TestClient) -> None:
    default = _source_id(user, "일반사이트")
    res = user.delete(f"/api/sources/{default}")
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "default_source"
    assert len(_sources(user)) == 5


def test_delete_source_moves_scraps_to_default(user: TestClient, clock: FakeClock) -> None:
    yt = _source_id(user, "유튜브")
    default = _source_id(user, "일반사이트")
    scrap = user.post("/api/scraps", json={"url": "https://youtu.be/abc"}).json()
    assert scrap["source"]["id"] == yt
    clock.advance(100)

    assert user.delete(f"/api/sources/{yt}").status_code == 204
    after = user.get(f"/api/scraps/{scrap['id']}").json()
    assert after["source"] == {"id": default, "name": "일반사이트"}
    assert after["updated_at"] == scrap["updated_at"]
    # 패턴도 함께 지워져 이후 판별은 기본 출처
    assert _detect(user, "https://youtube.com/watch?v=1") == default
    assert user.delete(f"/api/sources/{yt}").status_code == 404


def test_source_order(user: TestClient) -> None:
    ids = [s["id"] for s in _sources(user)]
    new = list(reversed(ids))
    res = user.put("/api/sources/order", json={"ids": new})
    assert res.status_code == 204
    assert [s["id"] for s in _sources(user)] == new
    # 새 출처는 맨 뒤
    created = user.post("/api/sources", json={"name": "새"}).json()
    assert _sources(user)[-1]["id"] == created["id"]


@pytest.mark.parametrize(
    "transform",
    [
        lambda ids: ids[:-1],  # 빠짐
        lambda ids: [*ids, ids[0]],  # 중복
        lambda ids: [*ids, 999],  # 없는 id
        lambda ids: [],
    ],
)
def test_source_order_must_be_complete(user: TestClient, transform) -> None:
    ids = [s["id"] for s in _sources(user)]
    res = user.put("/api/sources/order", json={"ids": transform(ids)})
    assert res.status_code == 400
    assert [s["id"] for s in _sources(user)] == ids


# ── 출처 자동 판별 ───────────────────────────────────


@pytest.mark.parametrize(
    ("url", "name"),
    [
        ("https://www.youtube.com/watch?v=1", "유튜브"),
        ("https://m.youtube.com/watch?v=1", "유튜브"),
        ("https://YOUTU.BE/abc", "유튜브"),
        ("https://youtube.com:443/x", "유튜브"),
        ("https://youtube.com./x", "유튜브"),
        ("https://x.com/someone/status/1", "X"),
        ("https://mobile.twitter.com/a", "X"),
        ("https://www.daangn.com/articles/1", "당근"),
        ("https://notyoutube.com/", "일반사이트"),
        ("https://youtube.com.example.test/", "일반사이트"),
        ("https://example.test/youtube.com", "일반사이트"),
    ],
)
def test_detect_source(user: TestClient, url: str, name: str) -> None:
    assert _detect(user, url) == _source_id(user, name)


def test_longest_pattern_wins(user: TestClient) -> None:
    shorts = user.post(
        "/api/sources", json={"name": "쇼츠", "domain_patterns": ["m.youtube.com"]}
    ).json()
    assert _detect(user, "https://m.youtube.com/shorts/1") == shorts["id"]
    assert _detect(user, "https://a.m.youtube.com/") == shorts["id"]
    assert _detect(user, "https://www.youtube.com/") == _source_id(user, "유튜브")


def test_explicit_source_overrides_detection(user: TestClient) -> None:
    community = _source_id(user, "커뮤니티")
    res = user.post(
        "/api/scraps", json={"url": "https://youtube.com/watch?v=1", "source_id": community}
    )
    assert res.json()["source"]["id"] == community


# ── 주제 ────────────────────────────────────────────


def test_topic_crud(user: TestClient) -> None:
    res = user.post("/api/topics", json={"name": " claude "})
    assert res.status_code == 201
    claude = res.json()
    assert claude == {"id": claude["id"], "name": "claude"}

    for name in ("Claude", "CLAUDE ", "claude"):
        dup = user.post("/api/topics", json={"name": name})
        assert dup.status_code == 400
        assert dup.json()["error"]["code"] == "duplicate_name"

    docker = user.post("/api/topics", json={"name": "docker"}).json()
    assert [t["name"] for t in user.get("/api/topics").json()] == ["claude", "docker"]

    res = user.patch(f"/api/topics/{claude['id']}", json={"name": "Claude"})
    assert res.status_code == 200
    assert res.json()["name"] == "Claude"
    res = user.patch(f"/api/topics/{claude['id']}", json={"name": "Docker"})
    assert res.json()["error"]["code"] == "duplicate_name"

    assert (
        user.put("/api/topics/order", json={"ids": [docker["id"], claude["id"]]}).status_code == 204
    )
    assert [t["name"] for t in user.get("/api/topics").json()] == ["docker", "Claude"]

    assert user.delete(f"/api/topics/{docker['id']}").status_code == 204
    assert user.delete(f"/api/topics/{docker['id']}").status_code == 404
    assert user.patch(f"/api/topics/{docker['id']}", json={"name": "z"}).status_code == 404
    assert user.patch(f"/api/topics/{2**70}", json={"name": "z"}).status_code == 404


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "가" * 31}, {"name": "a", "x": 1}])
def test_topic_input_rules(user: TestClient, body: dict) -> None:
    res = user.post("/api/topics", json=body)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_input"


def test_delete_topic_removes_from_scraps_only(user: TestClient, clock: FakeClock) -> None:
    a = user.post("/api/topics", json={"name": "a-topic"}).json()
    b = user.post("/api/topics", json={"name": "b-topic"}).json()
    scrap = user.post(
        "/api/scraps", json={"url": "https://e.test/", "topic_ids": [a["id"], b["id"]]}
    ).json()
    clock.advance(100)
    assert user.delete(f"/api/topics/{a['id']}").status_code == 204
    after = user.get(f"/api/scraps/{scrap['id']}").json()
    assert after["topics"] == [b]
    assert after["updated_at"] == scrap["updated_at"]


def test_topic_order_validation(user: TestClient) -> None:
    a = user.post("/api/topics", json={"name": "a"}).json()["id"]
    assert user.put("/api/topics/order", json={"ids": []}).status_code == 400
    assert user.put("/api/topics/order", json={"ids": [a, a]}).status_code == 400
    assert user.put("/api/topics/order", json={"ids": ["1"]}).status_code == 400
    assert user.put("/api/topics/order", json={"ids": [a]}).status_code == 204
