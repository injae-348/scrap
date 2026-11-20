"""스크랩 API: CRUD·좋아요·목록 필터·정렬·커서·검색·검색 색인 (docs/API.md v1.3)."""

import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.clock import KST
from tests.conftest import FakeClock

SCRAP_KEYS = {
    "id",
    "url",
    "title",
    "memo",
    "source",
    "topics",
    "liked",
    "due_date",
    "created_at",
    "updated_at",
}


def _create(client: TestClient, **body) -> dict:
    body.setdefault("url", "https://example.test/page")
    res = client.post("/api/scraps", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def _topic(client: TestClient, name: str) -> int:
    res = client.post("/api/topics", json={"name": name})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _list(client: TestClient, **params) -> dict:
    res = client.get("/api/scraps", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def _ids(client: TestClient, **params) -> list[int]:
    return [s["id"] for s in _list(client, **params)["items"]]


def _all_pages(client: TestClient, **params) -> list[int]:
    seen: list[int] = []
    cursor = None
    for _ in range(100):
        query = dict(params)
        if cursor:
            query["cursor"] = cursor
        page = _list(client, **query)
        seen.extend(s["id"] for s in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            return seen
    raise AssertionError("페이지가 끝나지 않음")


def _today(clock: FakeClock):
    return datetime.fromtimestamp(clock.now(), KST).date()


# ── 생성·조회 ────────────────────────────────────────


def test_create_minimal(user: TestClient) -> None:
    scrap = _create(user, url="  https://example.test/a  ")
    assert set(scrap) == SCRAP_KEYS
    assert scrap["url"] == "https://example.test/a"
    assert scrap["title"] == "https://example.test/a"  # 제목이 없으면 URL
    assert scrap["memo"] == ""
    assert scrap["source"]["name"] == "일반사이트"
    assert scrap["topics"] == []
    assert scrap["liked"] is False
    assert scrap["due_date"] is None
    assert scrap["created_at"].endswith("+09:00")
    assert scrap["created_at"] == scrap["updated_at"]
    assert user.get(f"/api/scraps/{scrap['id']}").json() == scrap


def test_create_full(user: TestClient) -> None:
    b = _topic(user, "b")
    a = _topic(user, "a")
    scrap = _create(
        user,
        url="http://example.test/b",
        title="  2026 공모전  ",
        memo="# 메모\n\n본문",
        source_id=5,
        topic_ids=[a, b, a],
        due_date="2026-12-31",
        liked=True,
    )
    assert scrap["title"] == "2026 공모전"
    assert scrap["memo"] == "# 메모\n\n본문"
    assert scrap["source"] == {"id": 5, "name": "커뮤니티"}
    # 중복은 합치고, 주제의 사용자 지정 순서(b가 먼저 생성)로 반환
    assert scrap["topics"] == [{"id": b, "name": "b"}, {"id": a, "name": "a"}]
    assert scrap["due_date"] == "2026-12-31"
    assert scrap["liked"] is True


def test_empty_title_uses_url(user: TestClient) -> None:
    assert _create(user, title="   ")["title"] == "https://example.test/page"
    assert _create(user, title=None)["title"] == "https://example.test/page"


def test_same_url_can_be_saved_twice(user: TestClient) -> None:
    a = _create(user, url="https://example.test/same")
    b = _create(user, url="https://example.test/same")
    assert a["id"] != b["id"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"url": ""},
        {"url": "ftp://example.test/"},
        {"url": "javascript:alert(1)"},
        {"url": "https://user@example.test/"},
        {"url": "https://user:secret@example.test/"},
        {"url": "http://user@x.com.evil.test/"},
        {"url": "https://:@example.test/"},
        {"url": "file:///etc/passwd"},
        {"url": "https://"},
        {"url": "example.test"},
        {"url": "https://exa mple.test/"},
        {"url": "https://example.test/\na"},
        {"url": "https://example.test/\x00"},
        {"url": "https://example.test:99999/"},
        {"url": "https://example.test/" + "a" * 2030},
        {"url": 123},
        {"url": "https://e.test", "title": "가" * 301},
        {"url": "https://e.test", "memo": "가" * 100_001},
        {"url": "https://e.test", "memo": None},
        {"url": "https://e.test", "source_id": 999},
        {"url": "https://e.test", "source_id": "1"},
        {"url": "https://e.test", "source_id": 2**70},
        {"url": "https://e.test", "topic_ids": [999]},
        {"url": "https://e.test", "topic_ids": "1"},
        {"url": "https://e.test", "topic_ids": [True]},
        {"url": "https://e.test", "due_date": "2026-02-30"},
        {"url": "https://e.test", "due_date": "2026-1-1"},
        {"url": "https://e.test", "due_date": "2026-12-31T00:00:00"},
        {"url": "https://e.test", "due_date": 20261231},
        {"url": "https://e.test", "liked": "true"},
        {"url": "https://e.test", "liked": 1},
        {"url": "https://e.test", "id": 1},
        {"url": "https://e.test", "created_at": "2026-01-01"},
    ],
)
def test_create_validation(user: TestClient, body: dict) -> None:
    res = user.post("/api/scraps", json=body)
    assert res.status_code == 400, res.text
    assert res.json()["error"]["code"] == "invalid_input"


def test_limits_are_inclusive(user: TestClient) -> None:
    url = "https://example.test/" + "a" * (2048 - len("https://example.test/"))
    scrap = _create(user, url=url, title="가" * 300, memo="가" * 100_000)
    assert len(scrap["url"]) == 2048


def test_topic_count_limit(user: TestClient) -> None:
    ids = [_topic(user, f"t{i}") for i in range(21)]
    res = user.post("/api/scraps", json={"url": "https://e.test", "topic_ids": ids})
    assert res.status_code == 400
    assert len(_create(user, topic_ids=ids[:20] + ids[:5])["topics"]) == 20


def test_get_missing(user: TestClient) -> None:
    for sid in ("999", "0", "-5", str(2**70)):
        res = user.get(f"/api/scraps/{sid}")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"


# ── 수정·삭제·좋아요 ──────────────────────────────────


def test_patch_rejects_liked(user: TestClient) -> None:
    scrap = _create(user)
    res = user.patch(f"/api/scraps/{scrap['id']}", json={"liked": True})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_input"


def test_patch_fields(user: TestClient, clock: FakeClock) -> None:
    t1 = _topic(user, "one")
    t2 = _topic(user, "two")
    scrap = _create(user, url="https://youtube.com/watch?v=1", title="원래", topic_ids=[t1])
    clock.advance(60)

    # URL만 바꿔도 출처는 그대로, 제목도 그대로
    res = user.patch(f"/api/scraps/{scrap['id']}", json={"url": "https://x.com/a"})
    assert res.status_code == 200
    body = res.json()
    assert body["url"] == "https://x.com/a"
    assert body["source"]["name"] == "유튜브"
    assert body["title"] == "원래"
    assert body["updated_at"] > scrap["updated_at"]
    assert body["created_at"] == scrap["created_at"]

    clock.advance(60)
    res = user.patch(
        f"/api/scraps/{scrap['id']}",
        json={
            "title": "",
            "memo": "새 메모",
            "source_id": 2,
            "topic_ids": [t2],
            "due_date": "2027-01-01",
        },
    )
    body = res.json()
    assert body["title"] == "https://x.com/a"  # 빈 제목 → URL
    assert body["memo"] == "새 메모"
    assert body["source"] == {"id": 2, "name": "X"}
    assert body["topics"] == [{"id": t2, "name": "two"}]
    assert body["due_date"] == "2027-01-01"

    res = user.patch(f"/api/scraps/{scrap['id']}", json={"due_date": None})
    assert res.json()["due_date"] is None


def test_patch_without_change_keeps_updated_at(user: TestClient, clock: FakeClock) -> None:
    t = _topic(user, "t")
    scrap = _create(user, title="제목", topic_ids=[t])
    clock.advance(60)
    for body in ({}, {"title": "제목"}, {"topic_ids": [t, t]}, {"url": scrap["url"]}):
        res = user.patch(f"/api/scraps/{scrap['id']}", json=body)
        assert res.status_code == 200
        assert res.json()["updated_at"] == scrap["updated_at"], body
    res = user.patch(f"/api/scraps/{scrap['id']}", json={"topic_ids": []})
    assert res.json()["updated_at"] > scrap["updated_at"]


@pytest.mark.parametrize(
    "body",
    [
        {"url": None},
        {"memo": None},
        {"source_id": None},
        {"topic_ids": None},
        {"source_id": 999},
        {"topic_ids": [999]},
        {"url": "ftp://e.test"},
        {"title": "가" * 301},
        {"due_date": "tomorrow"},
        {"unknown": 1},
    ],
)
def test_patch_validation(user: TestClient, body: dict) -> None:
    scrap = _create(user)
    res = user.patch(f"/api/scraps/{scrap['id']}", json=body)
    assert res.status_code == 400
    assert user.get(f"/api/scraps/{scrap['id']}").json() == scrap


def test_patch_missing(user: TestClient) -> None:
    assert user.patch("/api/scraps/999", json={"memo": "x"}).status_code == 404


def test_delete(user: TestClient) -> None:
    scrap = _create(user)
    assert user.delete(f"/api/scraps/{scrap['id']}").status_code == 204
    assert user.get(f"/api/scraps/{scrap['id']}").status_code == 404
    assert user.delete(f"/api/scraps/{scrap['id']}").status_code == 404


def test_like(user: TestClient, clock: FakeClock) -> None:
    scrap = _create(user)
    clock.advance(60)
    for _ in range(2):  # 같은 값을 반복해도 결과 동일
        res = user.put(f"/api/scraps/{scrap['id']}/like", json={"liked": True})
        assert res.status_code == 200
        assert res.json() == {"liked": True}
    after = user.get(f"/api/scraps/{scrap['id']}").json()
    assert after["liked"] is True
    assert after["updated_at"] == scrap["updated_at"]  # 좋아요는 updated_at을 바꾸지 않는다
    assert user.put(f"/api/scraps/{scrap['id']}/like", json={"liked": False}).json() == {
        "liked": False
    }
    for body in ({}, {"liked": "true"}, {"liked": None}, {"liked": True, "x": 1}):
        assert user.put(f"/api/scraps/{scrap['id']}/like", json=body).status_code == 400
    assert user.put("/api/scraps/999/like", json={"liked": True}).status_code == 404


# ── 목록 ────────────────────────────────────────────


def test_list_default_sort_created_desc(user: TestClient, clock: FakeClock) -> None:
    a = _create(user)["id"]
    b = _create(user)["id"]  # 같은 시각 → id 큰 순
    clock.advance(10)
    c = _create(user)["id"]
    page = _list(user)
    assert [s["id"] for s in page["items"]] == [c, b, a]
    assert page["next_cursor"] is None
    assert set(page["items"][0]) == SCRAP_KEYS


def test_list_sort_due(user: TestClient, clock: FakeClock) -> None:
    none_old = _create(user)["id"]
    late = _create(user, due_date="2027-03-01")["id"]
    clock.advance(10)
    early = _create(user, due_date="2027-01-01")["id"]
    late_newer = _create(user, due_date="2027-03-01")["id"]
    none_new = _create(user)["id"]
    assert _ids(user, sort="due") == [early, late_newer, late, none_new, none_old]


def test_list_filters(user: TestClient, clock: FakeClock) -> None:
    today = _today(clock)
    t1 = _topic(user, "one")
    t2 = _topic(user, "two")
    both = _create(user, topic_ids=[t1, t2], liked=True, due_date=today.isoformat())["id"]
    only1 = _create(user, topic_ids=[t1], due_date=(today + timedelta(days=7)).isoformat())["id"]
    yt = _create(user, url="https://youtu.be/x", due_date=(today + timedelta(days=8)).isoformat())
    past = _create(user, due_date=(today - timedelta(days=1)).isoformat(), liked=True)["id"]
    no_due = _create(user)["id"]

    assert set(_ids(user, topic_ids=f"{t1}")) == {both, only1}
    assert _ids(user, topic_ids=f"{t1},{t2}") == [both]  # AND
    assert _ids(user, topic_ids=f" {t2} , {t1} ") == [both]
    assert _ids(user, topic_ids=f"{t1},999") == []
    assert set(_ids(user, liked="true")) == {both, past}
    assert set(_ids(user, liked="false")) == {only1, yt["id"], no_due}
    assert set(_ids(user, due="upcoming")) == {both, only1}  # 오늘 ~ 오늘+7일
    assert _ids(user, due="past") == [past]
    assert _ids(user, source_id=str(yt["source"]["id"])) == [yt["id"]]
    assert _ids(user, source_id="999") == []
    assert _ids(user, source_id=str(2**70)) == []
    assert _ids(user, liked="true", due="past") == [past]
    assert len(_ids(user, topic_ids="")) == 5


@pytest.mark.parametrize(
    "params",
    [
        {"limit": "0"},
        {"limit": "101"},
        {"limit": "abc"},
        {"limit": "-1"},
        {"sort": "title"},
        {"liked": "yes"},
        {"due": "soon"},
        {"source_id": "abc"},
        {"source_id": "1.5"},
        {"topic_ids": "1,x"},
        {"topic_ids": "1,,2"},
        {"cursor": "not-a-cursor"},
        {"cursor": "W10"},  # base64("[]")
        {"q": "가" * 201},
        {"q": " ".join(f"w{i}" for i in range(11))},
        {"q": "abc\x00def"},
        {"q": "ab\x00"},
        {"q": "공모\x07전"},
        {"q": "a\tb"},
        {"q": "a\nb"},
        {"q": "\x7f"},
        {"source_id": "١٢"},
        {"topic_ids": "１"},
    ],
)
def test_list_validation(user: TestClient, params: dict) -> None:
    res = user.get("/api/scraps", params=params)
    assert res.status_code == 400, params
    assert res.json()["error"]["code"] == "invalid_input"


@pytest.mark.parametrize("sort", ["created", "due"])
def test_cursor_pagination(user: TestClient, clock: FakeClock, sort: str) -> None:
    dues = [None, "2027-01-01", "2027-01-01", None, "2026-12-01", "2027-02-01", None]
    for i, due in enumerate(dues):
        _create(user, due_date=due)
        if i % 2:
            clock.advance(5)  # 일부는 같은 시각 (id로 순서 결정)
    expected = _ids(user, sort=sort, limit="100")
    assert len(expected) == len(dues)
    for size in ("1", "2", "3"):
        assert _all_pages(user, sort=sort, limit=size) == expected


def test_cursor_from_other_sort_rejected(user: TestClient) -> None:
    for _ in range(3):
        _create(user)
    cursor = _list(user, limit="1")["next_cursor"]
    assert cursor
    res = user.get("/api/scraps", params={"sort": "due", "cursor": cursor})
    assert res.status_code == 400
    assert user.get("/api/scraps", params={"cursor": cursor}).status_code == 200


def test_limit_default_30(user: TestClient) -> None:
    for _ in range(31):
        _create(user)
    page = _list(user)
    assert len(page["items"]) == 30
    assert page["next_cursor"]


# ── 검색 ────────────────────────────────────────────


def test_search_fields_and_partial_match(user: TestClient) -> None:
    claude = _topic(user, "Claude")
    a = _create(user, url="https://contest.example.test/p", title="2026 대학생 공모전 안내")["id"]
    b = _create(user, memo="도커 컴포즈 설정 메모", topic_ids=[claude])["id"]
    c = _create(user, url="https://blog.example.test/kubernetes-guide")["id"]

    assert _ids(user, q="공모전") == [a]
    assert _ids(user, q="모전 안") == [a]  # 단어 각각: "모전"(2글자), "안"(1글자)
    assert _ids(user, q="컴포즈") == [b]
    assert _ids(user, q="claude") == [b]  # 주제 이름, 대소문자 무시
    assert _ids(user, q="CLAU") == [b]
    assert _ids(user, q="kubernetes") == [c]
    assert _ids(user, q="KUBERNETES-GUIDE") == [c]
    assert set(_ids(user, q="example")) == {a, b, c}
    assert _ids(user, q="example 공모전") == [a]  # 모든 단어 AND
    assert _ids(user, q="공모전 도커") == []
    assert len(_ids(user, q="   ")) == 3  # 빈 검색어는 무시


def test_search_short_words(user: TestClient) -> None:
    ai = _create(user, title="AI 뉴스 정리")["id"]
    go = _create(user, title="Go 언어", memo="입문")["id"]
    _create(user, title="기타")
    assert _ids(user, q="ai") == [ai]
    assert _ids(user, q="뉴") == [ai]
    assert _ids(user, q="go 입문") == [go]


@pytest.mark.parametrize(
    "q",
    [
        '"',
        '""',
        "*",
        "a*",
        "OR",
        "a OR b",
        "NOT",
        "NEAR(a b)",
        "title:abc",
        "(abc",
        "abc)",
        "^abc",
        "-abc",
        "a AND",
        "%",
        "_",
        "\\",
        "'; DROP TABLE scraps; --",
        '"unterminated',
    ],
)
def test_search_syntax_is_literal(user: TestClient, q: str) -> None:
    _create(user, title="평범한 제목")
    res = user.get("/api/scraps", params={"q": q})
    assert res.status_code == 200, (q, res.text)
    assert res.json()["items"] == []


def test_search_special_characters_match_literally(user: TestClient) -> None:
    cpp = _create(user, title="C++ 입문서")["id"]
    pct = _create(user, title="할인 50% 행사")["id"]
    under = _create(user, title="snake_case 규칙")["id"]
    quote = _create(user, title='책 "어린 왕자" 후기')["id"]
    star = _create(user, title="별점 ***** 맛집")["id"]
    _create(user, title="50 퍼센트 snakeXcase")
    assert _ids(user, q="c++") == [cpp]
    assert _ids(user, q="50%") == [pct]
    assert _ids(user, q="%") == [pct]
    assert _ids(user, q="e_c") == [under]
    assert _ids(user, q="_") == [under]
    assert _ids(user, q='"어린') == [quote]
    assert _ids(user, q="***") == [star]


def test_search_follows_sort_and_filters(user: TestClient, clock: FakeClock) -> None:
    old = _create(user, title="회의록 첫번째", due_date="2027-05-01")["id"]
    clock.advance(10)
    new = _create(user, title="회의록 두번째", due_date="2027-01-01", liked=True)["id"]
    assert _ids(user, q="회의록") == [new, old]
    assert _ids(user, q="회의록", sort="due") == [new, old]
    assert _ids(user, q="회의록", liked="true") == [new]
    assert _all_pages(user, q="회의록", limit="1") == [new, old]


# ── 검색 색인 동기화 ─────────────────────────────────


def _fts_rows(client: TestClient) -> dict[int, tuple]:
    conn = client.app.state.db.connect()
    try:
        return {
            r[0]: tuple(r[1:])
            for r in conn.execute("SELECT rowid, title, memo, url, topics FROM scraps_fts")
        }
    finally:
        conn.close()


def _expected_fts(client: TestClient) -> dict[int, tuple]:
    conn = client.app.state.db.connect()
    conn.row_factory = sqlite3.Row
    try:
        out = {}
        for s in conn.execute("SELECT id, title, memo, url FROM scraps"):
            names = sorted(
                r[0]
                for r in conn.execute(
                    "SELECT t.name FROM scrap_topics st JOIN topics t ON t.id = st.topic_id"
                    " WHERE st.scrap_id = ?",
                    (s["id"],),
                )
            )
            out[s["id"]] = (s["title"], s["memo"], s["url"], names)
        return out
    finally:
        conn.close()


def _assert_fts_in_sync(client: TestClient) -> None:
    actual = {
        k: (*v[:3], sorted(filter(None, v[3].split("\n")))) for k, v in _fts_rows(client).items()
    }
    assert actual == _expected_fts(client)


def test_fts_index_stays_in_sync(user: TestClient) -> None:
    t1 = _topic(user, "alpha-topic")
    t2 = _topic(user, "beta-topic")
    a = _create(user, title="첫 스크랩", topic_ids=[t1])["id"]
    b = _create(user, title="둘째 스크랩", memo="메모", topic_ids=[t1, t2])["id"]
    _assert_fts_in_sync(user)

    user.patch(
        f"/api/scraps/{a}", json={"title": "바뀐 제목", "memo": "새 메모", "url": "https://n.test"}
    )
    _assert_fts_in_sync(user)
    assert _ids(user, q="바뀐 제목") == [a]
    assert _ids(user, q="첫 스크랩") == []

    user.patch(f"/api/scraps/{a}", json={"topic_ids": [t2]})
    _assert_fts_in_sync(user)
    assert _ids(user, q="alpha-topic") == [b]

    user.patch(f"/api/topics/{t2}", json={"name": "gamma-topic"})
    _assert_fts_in_sync(user)
    assert _ids(user, q="beta-topic") == []
    assert set(_ids(user, q="gamma-topic")) == {a, b}

    user.delete(f"/api/topics/{t2}")
    _assert_fts_in_sync(user)
    assert _ids(user, q="gamma-topic") == []

    user.delete(f"/api/scraps/{b}")
    _assert_fts_in_sync(user)
    assert set(_fts_rows(user)) == {a}

    user.delete("/api/sources/1")  # 출처 삭제(스크랩 이동)도 색인을 깨지 않는다
    _assert_fts_in_sync(user)


def test_fts_uses_trigram_tokenizer(user: TestClient) -> None:
    conn = user.app.state.db.connect()
    try:
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'scraps_fts'").fetchone()[0]
    finally:
        conn.close()
    assert "trigram" in sql


# ── 날짜 경계·정렬 동률·검색 오류 처리 ─────────────────────


def _at_kst(clock: FakeClock, year: int, month: int, day: int, hh: int, mm: int, ss: int) -> None:
    target = datetime(year, month, day, hh, mm, ss, tzinfo=KST).timestamp()
    clock.advance(target - clock.now())


def test_due_filters_follow_kst_midnight(user: TestClient, clock: FakeClock) -> None:
    # 2027-03-10 23:59:59 KST = 2027-03-10 14:59:59 UTC. UTC 날짜와 KST 날짜가 1초 뒤 갈린다.
    _at_kst(clock, 2027, 3, 10, 23, 59, 59)
    on_10 = _create(user, due_date="2027-03-10")["id"]
    on_9 = _create(user, due_date="2027-03-09")["id"]
    on_17 = _create(user, due_date="2027-03-17")["id"]
    on_18 = _create(user, due_date="2027-03-18")["id"]

    assert set(_ids(user, due="upcoming")) == {on_10, on_17}
    assert _ids(user, due="past") == [on_9]

    clock.advance(1)  # 2027-03-11 00:00:00 KST (UTC로는 아직 03-10)
    assert datetime.fromtimestamp(clock.now(), KST).date().isoformat() == "2027-03-11"
    assert set(_ids(user, due="upcoming")) == {on_17, on_18}
    assert set(_ids(user, due="past")) == {on_9, on_10}


def test_sort_due_ties_broken_by_id(user: TestClient) -> None:
    # 같은 마감일·같은 created_at (가짜 시계가 멈춰 있음) → id 큰 순. 마감일 없는 것끼리도 같다.
    same = [_create(user, due_date="2027-05-01")["id"] for _ in range(4)]
    nulls = [_create(user)["id"] for _ in range(3)]
    expected = list(reversed(same)) + list(reversed(nulls))
    assert _ids(user, sort="due") == expected
    for size in ("1", "2", "3"):
        assert _all_pages(user, sort="due", limit=size) == expected


def test_search_database_error_is_400(user: TestClient, monkeypatch) -> None:
    import app.scraps as scraps_module

    def broken(words: list[str]) -> tuple[list[str], list[object]]:
        return (
            ["s.id IN (SELECT rowid FROM scraps_fts WHERE scraps_fts MATCH ?)"],
            ['"unterminated'],
        )

    monkeypatch.setattr(scraps_module, "search_conditions", broken)
    res = user.get("/api/scraps", params={"q": "anything"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_input"
