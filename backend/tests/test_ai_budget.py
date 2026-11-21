"""AI 하루 토큰 예산·하루 요청 횟수 문구 (docs/API.md v1.6). Claude는 가짜(`FakeAnthropic`)."""

import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.limits import response_tokens
from app.config import DEFAULT_AI_TOKENS_PER_DAY, Settings
from tests.conftest import FAKE_SESSION_SECRET, FakeClock, do_setup
from tests.test_ai import (
    FAKE_KEY,
    SECONDS_TO_MIDNIGHT,
    TODAY,
    URL,
    FakeAnthropic,
    extract_result,
    install,
    json_reply,
    make_scrap,
    tool_reply,
)

BUDGET_MESSAGE = "오늘 AI 사용량을 모두 썼어요. 내일 다시 시도해 주세요."
DAILY_MESSAGE = "오늘 AI 요청 횟수를 모두 썼어요. 내일 다시 시도해 주세요."
MINUTE_MESSAGE = "AI 요청이 너무 많아요. 잠시 후 다시 시도해 주세요."


def with_usage(reply: SimpleNamespace, **tokens: int) -> SimpleNamespace:
    reply.usage = SimpleNamespace(
        input_tokens=tokens.get("i", 0),
        cache_creation_input_tokens=tokens.get("cw", 0),
        cache_read_input_tokens=tokens.get("cr", 0),
        output_tokens=tokens.get("o", 0),
    )
    return reply


def day_rows(client: TestClient) -> dict[str, tuple[int, int]]:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    try:
        rows = conn.execute("SELECT day, count, tokens FROM ai_usage_days").fetchall()
    finally:
        conn.close()
    return {day: (count, tokens) for day, count, tokens in rows}


@pytest.fixture
def budget(
    make_client, clock: FakeClock, tmp_path, monkeypatch
) -> tuple[TestClient, FakeAnthropic]:
    import app.ai.claude as claude_module

    monkeypatch.setattr(claude_module, "RETRY_DELAY_SECONDS", 0.0)
    client = make_client(
        clock=clock,
        DB_PATH=str(tmp_path / "budget.db"),
        ANTHROPIC_API_KEY=FAKE_KEY,
        AI_TOKENS_PER_DAY="1000",
        AI_PER_MINUTE="100",
    )
    do_setup(client, clock)
    fake = FakeAnthropic()
    install(client, fake)
    return client, fake


def extract(client: TestClient) -> Any:
    return client.post("/api/ai/extract", json={"url": URL, "text": "본문"})


# ── 설정 ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, DEFAULT_AI_TOKENS_PER_DAY),
        ("", DEFAULT_AI_TOKENS_PER_DAY),
        ("1", 1),
        ("2500000", 2_500_000),
        ("100000000", 100_000_000),
        ("100000001", DEFAULT_AI_TOKENS_PER_DAY),
        ("0", DEFAULT_AI_TOKENS_PER_DAY),
        ("-5", DEFAULT_AI_TOKENS_PER_DAY),
        ("1e6", DEFAULT_AI_TOKENS_PER_DAY),
        ("１００", DEFAULT_AI_TOKENS_PER_DAY),  # 전각 숫자
        ("9" * 5000, DEFAULT_AI_TOKENS_PER_DAY),
    ],
)
def test_tokens_per_day_setting(make_client, clock, tmp_path, caplog, raw, expected) -> None:
    env = {"DB_PATH": str(tmp_path / "t.db")}
    if raw is not None:
        env["AI_TOKENS_PER_DAY"] = raw
    client = make_client(clock=clock, **env)
    settings: Settings = client.app.state.settings
    assert settings.ai_tokens_per_day == expected
    assert client.app.state.ai_limiter.tokens_per_day == expected
    warned = any("AI_TOKENS_PER_DAY" in r.getMessage() for r in caplog.records)
    assert warned == (raw not in (None, "") and expected == DEFAULT_AI_TOKENS_PER_DAY)


def test_settings_default_tokens() -> None:
    s = Settings(db_path="x", enable_api_docs=False, session_secret=FAKE_SESSION_SECRET)
    assert s.ai_tokens_per_day == 1_000_000


def test_response_tokens_sums_all_usage_fields() -> None:
    reply = with_usage(SimpleNamespace(), i=10, cw=20, cr=30, o=40)
    assert response_tokens(reply) == 100
    assert response_tokens(SimpleNamespace()) == 0
    # 빠진 항목(None)·이상한 값은 0으로 본다
    odd = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=5, cache_creation_input_tokens=None, output_tokens=True)
    )
    assert response_tokens(odd) == 5
    assert response_tokens(SimpleNamespace(usage={"input_tokens": 3, "output_tokens": 4})) == 7


# ── 누적 ────────────────────────────────────────────


def test_tokens_accumulate_per_day(budget, clock: FakeClock) -> None:
    client, fake = budget
    fake.add(with_usage(json_reply(extract_result()), i=100, cw=10, cr=5, o=50))
    assert extract(client).status_code == 200
    fake.add(with_usage(json_reply(extract_result()), i=1, o=2))
    assert extract(client).status_code == 200
    assert day_rows(client) == {TODAY: (2, 168)}

    clock.advance(SECONDS_TO_MIDNIGHT)  # 다음 날 (Asia/Seoul)
    fake.add(with_usage(json_reply(extract_result()), i=7))
    assert extract(client).status_code == 200
    assert day_rows(client) == {TODAY: (2, 168), "2027-01-16": (1, 7)}


@pytest.mark.parametrize(
    "reply",
    [
        json_reply(extract_result(), stop="refusal"),
        json_reply(extract_result(), stop="max_tokens"),
        json_reply("JSON 아님"),
    ],
)
def test_failed_calls_with_usage_are_counted(budget, reply) -> None:
    client, fake = budget
    fake.add(with_usage(reply, i=40, o=60))
    res = extract(client)
    assert res.status_code == 502
    assert day_rows(client) == {TODAY: (1, 100)}


# ── 예산 초과 ───────────────────────────────────────


def test_budget_exhausted_blocks_until_midnight(budget, clock: FakeClock) -> None:
    client, fake = budget
    # 한 요청이 예산을 넘겨도 그 요청은 끝까지 처리하고 사용량은 모두 누적한다.
    fake.add(with_usage(json_reply(extract_result()), i=900, o=300))
    assert extract(client).status_code == 200
    assert day_rows(client) == {TODAY: (1, 1200)}

    for res in (extract(client), client.post("/api/ai/search", json={"query": "x"})):
        assert res.status_code == 429
        assert res.json()["error"] == {"code": "ai_daily_limit", "message": BUDGET_MESSAGE}
        # 다음 Asia/Seoul 자정까지 (do_setup 이 30초 넘겼다)
        assert int(res.headers["retry-after"]) == SECONDS_TO_MIDNIGHT - 30
    assert len(fake.calls) == 1
    assert day_rows(client) == {TODAY: (1, 1200)}  # 막힌 요청은 횟수에 넣지 않는다
    assert client.app.state.ai_limiter._active == 0

    clock.advance(SECONDS_TO_MIDNIGHT)
    fake.add(json_reply(extract_result()))
    assert extract(client).status_code == 200


def test_budget_checked_before_each_search_round(budget) -> None:
    client, fake = budget
    make_scrap(client, "대학생 공모전")
    fake.add(
        with_usage(tool_reply("공모전"), i=600),
        with_usage(tool_reply("대회"), i=500),  # 여기서 예산(1000)을 넘는다
        json_reply({"answer": "x", "results": []}),  # 부르지 않는다
    )
    res = client.post("/api/ai/search", json={"query": "공모전"})
    assert res.status_code == 429
    assert res.json()["error"] == {"code": "ai_daily_limit", "message": BUDGET_MESSAGE}
    assert int(res.headers["retry-after"]) >= 600
    assert len(fake.calls) == 2
    assert day_rows(client) == {TODAY: (1, 1100)}
    assert client.app.state.ai_limiter._active == 0


def test_budget_not_reached_lets_search_finish(budget) -> None:
    client, fake = budget
    fake.add(
        with_usage(tool_reply("공모전"), i=300),
        with_usage(json_reply({"answer": "없어요", "results": []}), i=400),
    )
    res = client.post("/api/ai/search", json={"query": "공모전"})
    assert res.status_code == 200, res.text
    assert day_rows(client) == {TODAY: (1, 700)}


# ── 문구 구분 (분당·하루 횟수·하루 토큰) ─────────────


def test_limit_messages_are_distinct(make_client, clock: FakeClock, tmp_path) -> None:
    client = make_client(
        clock=clock,
        DB_PATH=str(tmp_path / "m.db"),
        ANTHROPIC_API_KEY=FAKE_KEY,
        AI_PER_DAY="2",
        AI_PER_MINUTE="1",
    )
    do_setup(client, clock)
    fake = FakeAnthropic()
    install(client, fake)

    fake.add(json_reply(extract_result()))
    assert extract(client).status_code == 200
    minute = extract(client)  # 분당 1회
    assert minute.status_code == 429
    assert minute.json()["error"] == {"code": "too_many_requests", "message": MINUTE_MESSAGE}
    assert int(minute.headers["retry-after"]) <= 60

    clock.advance(61)
    fake.add(json_reply(extract_result()))
    assert extract(client).status_code == 200
    clock.advance(61)
    daily = extract(client)  # 하루 2회
    assert daily.status_code == 429
    assert daily.json()["error"] == {"code": "ai_daily_limit", "message": DAILY_MESSAGE}
    assert int(daily.headers["retry-after"]) == SECONDS_TO_MIDNIGHT - 30 - 122

    # 동시 처리 초과는 기존 문구
    clock.advance(SECONDS_TO_MIDNIGHT)
    limiter = client.app.state.ai_limiter
    limiter.per_minute = limiter.per_day = 100
    held = [limiter.begin(), limiter.begin()]
    busy = extract(client)
    assert busy.status_code == 429
    assert busy.json()["error"] == {"code": "too_many_requests", "message": MINUTE_MESSAGE}
    assert busy.headers["retry-after"] == "5"
    for ticket in held:
        limiter.finish(ticket)


# ── 마이그레이션 (추가형) ────────────────────────────


def test_tokens_column_is_additive(tmp_path) -> None:
    """0005 이후 DB에서도 0004까지만 아는 이전 코드의 SQL이 그대로 동작한다."""
    from app.db import apply_migrations, list_migrations

    older = tmp_path / "older"
    older.mkdir()
    for _, name, path in list_migrations():
        if name < "0005":
            (older / name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    conn = sqlite3.connect(tmp_path / "m.db", isolation_level=None)
    try:
        apply_migrations(conn, now=0, directory=older)
        conn.execute("INSERT INTO ai_usage_days (day, count) VALUES ('2027-01-14', 5)")
        assert apply_migrations(conn, now=0) >= 1  # 0005 적용
        assert conn.execute("SELECT count, tokens FROM ai_usage_days").fetchall() == [(5, 0)]
        # 이전 코드(0004 시절 limits.py)의 쓰기·읽기
        for _ in range(2):
            conn.execute(
                "INSERT INTO ai_usage_days (day, count) VALUES (?, 1)"
                " ON CONFLICT (day) DO UPDATE SET count = count + 1",
                ("2027-01-15",),
            )
        row = conn.execute("SELECT count FROM ai_usage_days WHERE day = ?", ("2027-01-15",))
        assert row.fetchone() == (2,)
        assert conn.execute(
            "SELECT tokens FROM ai_usage_days WHERE day = '2027-01-15'"
        ).fetchone() == (0,)
    finally:
        conn.close()


def test_retry_after_until_midnight_is_at_least_one_second() -> None:
    from app.ai.limits import seconds_until_next_day

    midnight = 1_800_000_000 + SECONDS_TO_MIDNIGHT  # 2027-01-16 00:00 (Asia/Seoul)
    assert seconds_until_next_day(midnight - 0.2) == 1
    assert seconds_until_next_day(midnight - 30) == 30
    assert seconds_until_next_day(midnight) == 86_400


def test_budget_near_midnight_still_ai_daily_limit(budget, clock: FakeClock) -> None:
    client, fake = budget
    fake.add(with_usage(json_reply(extract_result()), i=2000))
    assert extract(client).status_code == 200
    clock.advance(SECONDS_TO_MIDNIGHT - 30 - 5)  # 자정 5초 전
    res = extract(client)
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "ai_daily_limit"
    assert res.headers["retry-after"] == "5"
