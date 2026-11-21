"""AI API `/api/ai/extract`·`/api/ai/search` (docs/API.md v1.5 "AI 세부 규칙").

Claude API는 절대 실제로 부르지 않는다: `ClaudeGateway`에 가짜 클라이언트(`FakeAnthropic`)를 넣는다.
페이지 가져오기는 tests/test_preview.py 의 가짜 DNS·연결(StubServer)을 쓴다.
"""

import asyncio
import json
import logging
import sqlite3
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

import app.ai.claude as claude_module
import app.ai.router as router_module
from app.ai.claude import FALLBACK_BETA, ClaudeGateway
from app.ai.prompts import EXTRACT_SCHEMA, MAX_TOOL_CALLS, SEARCH_SCHEMA, TOOL_LIMIT_NOTICE
from app.config import Settings
from app.pagetext import PageTextFetcher
from app.preview import PreviewFetcher
from app.routing import api_endpoints
from tests.conftest import FAKE_SESSION_SECRET, FakeClock
from tests.test_fetch import article
from tests.test_preview import PUBLIC_IP, YOUTUBE_IP, StubServer, http_response

# 테스트 전용 가짜 키 (실제 키 아님, 형식만 맞춘다).
FAKE_KEY = "sk-ant-test-only-fake-key-0000000000"
TODAY = "2027-01-15"  # FakeClock 시작 시각(1_800_000_000)의 Asia/Seoul 날짜, 17:00
SECONDS_TO_MIDNIGHT = 7 * 3600
URL = "https://site.example.test/post/1"

# ── 가짜 Claude ─────────────────────────────────────


def block(kind: str, **fields: Any) -> SimpleNamespace:
    return SimpleNamespace(type=kind, **fields)


def json_reply(data: object, stop: str = "end_turn") -> SimpleNamespace:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return SimpleNamespace(
        stop_reason=stop,
        content=[block("thinking", thinking="", signature="sig"), block("text", text=text)],
    )


def tool_reply(*queries: str, name: str = "search_scraps") -> SimpleNamespace:
    uses = [
        block("tool_use", id=f"toolu_{i}_{q}", name=name, input={"query": q})
        for i, q in enumerate(queries)
    ]
    return SimpleNamespace(stop_reason="tool_use", content=[block("thinking", thinking=""), *uses])


Step = SimpleNamespace | BaseException | Callable[[dict[str, Any]], Any]


class FakeMessages:
    def __init__(self, script: list[Step]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("예상보다 많이 호출됨")
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            result = step(kwargs)
            return await result if asyncio.iscoroutine(result) else result
        return step


class FakeAnthropic:
    def __init__(self, script: list[Step] | None = None) -> None:
        self.messages = FakeMessages(script or [])
        self.beta = SimpleNamespace(messages=self.messages)

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.messages.calls

    def add(self, *steps: Step) -> None:
        self.messages.script.extend(steps)


def install(client: TestClient, fake: FakeAnthropic) -> list[str]:
    """가짜 클라이언트를 넣는다. 반환: 클라이언트를 만들 때 받은 키 목록 (지연 생성 확인용)."""
    created: list[str] = []

    def factory(key: str) -> FakeAnthropic:
        created.append(key)
        return fake

    client.app.state.ai_gateway = ClaudeGateway(FAKE_KEY, "claude-opus-5-5", client_factory=factory)
    return created


@pytest.fixture
def fake() -> FakeAnthropic:
    return FakeAnthropic()


@pytest.fixture
def ai(user: TestClient, fake: FakeAnthropic, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    install(user, fake)
    monkeypatch.setattr(claude_module, "RETRY_DELAY_SECONDS", 0.0)
    return user


def use_server(client: TestClient, server: StubServer) -> None:
    client.app.state.page_fetcher = PageTextFetcher(
        resolver=server.resolve, backend_factory=server.backend
    )
    client.app.state.preview_fetcher = PreviewFetcher(
        resolver=server.resolve, backend_factory=server.backend
    )


def usage(client: TestClient) -> dict[str, int]:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    try:
        return dict(conn.execute("SELECT day, count FROM ai_usage_days").fetchall())
    finally:
        conn.close()


def extract_result(**overrides: Any) -> dict[str, Any]:
    data = {
        "title": "공모전 안내",
        "due_date": "2027-01-22",
        "memo": "- 대학생 대상\n- 상금 100만 원",
        "topic_suggestions": ["공모전"],
    }
    data.update(overrides)
    return data


def api_error(cls: type, status: int, error_type: str, message: str, code: str | None = None):
    error: dict[str, Any] = {"type": error_type, "message": message}
    if code:
        error["details"] = {"error_code": code}
    body = {"type": "error", "error": error}
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, request=request, json=body, headers={"request-id": "req_x"})
    return cls(message, response=response, body=body)


def connection_error() -> Exception:
    return anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )


def make_topic(client: TestClient, name: str) -> int:
    res = client.post("/api/topics", json={"name": name})
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


def make_scrap(client: TestClient, title: str, memo: str = "", **extra: Any) -> int:
    url = f"https://ex.test/p/{len(client.get('/api/scraps?limit=100').json()['items'])}"
    res = client.post("/api/scraps", json={"url": url, "title": title, "memo": memo, **extra})
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


# ── 설정·사용 가능 여부 ───────────────────────────────


@pytest.mark.parametrize("key", [None, "", "sk-ant-xxxx", "sk-test-123", "  ", "sk-ant- bad"])
def test_ai_unavailable_without_valid_key(make_client, clock, tmp_path, key) -> None:
    env = {"DB_PATH": str(tmp_path / "t.db")}
    if key is not None:
        env["ANTHROPIC_API_KEY"] = key
    client = make_client(clock=clock, **env)
    assert client.get("/api/health").status_code == 200  # 앱은 정상 기동
    from tests.conftest import do_setup

    do_setup(client, clock)
    for path, body in (("/api/ai/extract", {"url": URL}), ("/api/ai/search", {"query": "x"})):
        res = client.post(path, json=body)
        assert res.status_code == 503
        assert res.json()["error"]["code"] == "ai_unavailable"
    assert usage(client) == {}


def test_input_error_comes_before_unavailable(user: TestClient) -> None:
    res = user.post("/api/ai/extract", json={"url": "ftp://x.test/"})
    assert res.status_code == 400
    res = user.post("/api/ai/search", json={"query": "  "})
    assert res.status_code == 400


def test_key_never_in_repr_logs_or_responses(make_client, clock, tmp_path, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(claude_module, "RETRY_DELAY_SECONDS", 0.0)
    client = make_client(clock=clock, DB_PATH=str(tmp_path / "t.db"), ANTHROPIC_API_KEY=FAKE_KEY)
    settings: Settings = client.app.state.settings
    assert settings.ai_available
    assert FAKE_KEY not in repr(settings)
    assert FAKE_KEY not in repr(client.app.state.ai_gateway)
    assert FAKE_KEY not in str(client.app.state.ai_gateway.__dict__.get("model"))

    from tests.conftest import do_setup

    do_setup(client, clock)
    # 외부 오류 문구에 키가 들어 있어도 응답·로그에 나오지 않는다.
    leaky = api_error(anthropic.AuthenticationError, 401, "authentication_error", f"bad {FAKE_KEY}")
    fake = FakeAnthropic([leaky, ValueError(f"oops {FAKE_KEY}")])
    created = install(client, fake)
    res = client.post("/api/ai/extract", json={"url": URL, "text": "본문 " * 10})
    assert res.status_code == 502
    assert FAKE_KEY not in res.text
    res = client.post("/api/ai/extract", json={"url": URL, "text": "본문 " * 10})
    assert res.status_code == 502
    assert created == [FAKE_KEY]  # 키는 클라이언트 생성에만 쓰인다 (한 번)
    assert FAKE_KEY not in caplog.text
    assert "본문 본문" not in caplog.text  # 본문도 로그에 남기지 않는다


def test_client_created_lazily_only_with_valid_key(make_client, clock, tmp_path) -> None:
    client = make_client(clock=clock, DB_PATH=str(tmp_path / "t.db"), ANTHROPIC_API_KEY=FAKE_KEY)
    gateway: ClaudeGateway = client.app.state.ai_gateway
    assert gateway.available and gateway._client is None  # 요청 전에는 만들지 않는다
    none = ClaudeGateway(None, "claude-opus-5-5", client_factory=lambda k: pytest.fail("생성됨"))
    assert not none.available


def test_settings_model_and_limits(make_client, clock, tmp_path) -> None:
    client = make_client(
        clock=clock,
        DB_PATH=str(tmp_path / "t.db"),
        ANTHROPIC_MODEL="claude-sonnet-5-5",
        AI_PER_MINUTE="3",
        AI_PER_DAY="50",
    )
    s: Settings = client.app.state.settings
    assert (s.anthropic_model, s.ai_per_minute, s.ai_per_day) == ("claude-sonnet-5-5", 3, 50)
    bad = make_client(
        clock=clock,
        DB_PATH=str(tmp_path / "u.db"),
        ANTHROPIC_MODEL="bad model!",
        AI_PER_MINUTE="0",
        AI_PER_DAY="lots",
    )
    s = bad.app.state.settings
    assert (s.anthropic_model, s.ai_per_minute, s.ai_per_day) == ("claude-opus-5-5", 10, 200)
    direct = Settings(
        db_path="x", enable_api_docs=False, session_secret=FAKE_SESSION_SECRET, anthropic_api_key=""
    )
    assert direct.anthropic_api_key is None


def test_ai_routes_require_session(client: TestClient) -> None:
    protected = {(m, p) for m, p, _ in api_endpoints(client.app)}
    assert {("POST", "/api/ai/extract"), ("POST", "/api/ai/search")} <= protected
    for path in ("/api/ai/extract", "/api/ai/search"):
        res = client.post(path, json={"url": URL, "query": "x"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "unauthorized"


# ── AI로 채우기 ──────────────────────────────────────


def test_extract_with_pasted_text(ai: TestClient, fake: FakeAnthropic) -> None:
    make_topic(ai, "Claude")
    make_topic(ai, "공모전")
    server = StubServer()
    use_server(ai, server)
    fake.add(json_reply(extract_result(topic_suggestions=["claude", "새 주제"])))
    pasted = "  붙여넣은 공모전 본문. 마감은 다음 주 금요일. \r\n\t끝  "
    res = ai.post("/api/ai/extract", json={"url": URL, "text": pasted})
    assert res.status_code == 200, res.text
    assert res.json() == {
        "title": "공모전 안내",
        "due_date": "2027-01-22",
        "memo": "- 대학생 대상\n- 상금 100만 원",
        "topic_suggestions": ["Claude", "새 주제"],
        "content_fetched": True,
    }
    assert server.dns_queries == []  # 붙여넣은 본문이 있으면 페이지를 가져오지 않는다

    (call,) = fake.calls
    assert call["model"] == "claude-opus-5-5"
    assert call["betas"] == [FALLBACK_BETA]
    assert call["fallbacks"] == "default"
    assert call["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": EXTRACT_SCHEMA},
    }
    assert "thinking" not in call and "temperature" not in call and "tool_choice" not in call
    assert 0 < call["timeout"] <= 60
    (system,) = call["system"]
    assert system["cache_control"] == {"type": "ephemeral"}
    assert "데이터" in system["text"] and "따르지 말고" in system["text"]
    assert TODAY not in system["text"]  # 가변 값은 시스템 프롬프트(캐시되는 앞부분)에 넣지 않는다
    (message,) = call["messages"]
    assert message["role"] == "user"
    assert f"오늘 날짜(Asia/Seoul): {TODAY}" in message["content"]
    assert '["Claude", "공모전"]' in message["content"]
    assert pasted.strip() in message["content"]
    assert usage(ai) == {TODAY: 1}


def test_extract_short_pasted_text_still_calls_ai(ai: TestClient, fake: FakeAnthropic) -> None:
    """붙여넣은 본문에는 최소 길이가 없다 (200자 기준은 가져온 본문에만)."""
    fake.add(json_reply(extract_result()))
    res = ai.post("/api/ai/extract", json={"url": URL, "text": "짧"})
    assert res.status_code == 200
    assert res.json()["content_fetched"] is True
    assert len(fake.calls) == 1


@pytest.mark.parametrize(
    "text",
    [
        "가" * 50_001,
        "본문\x00",
        "본문\x07",
        "본문\x1b[0m",
    ],
)
def test_extract_pasted_text_rules(ai: TestClient, fake: FakeAnthropic, text: str) -> None:
    res = ai.post("/api/ai/extract", json={"url": URL, "text": text})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_input"
    assert fake.calls == []
    assert usage(ai) == {}


def sent_body(call: dict[str, Any]) -> str:
    content = call["messages"][0]["content"]
    start = content.index("\n", content.index("<page_content")) + 1
    return content[start : content.index("\n</page_content")]


def test_extract_pasted_text_limit_is_code_points(ai: TestClient, fake: FakeAnthropic) -> None:
    fake.add(json_reply(extract_result()))
    res = ai.post("/api/ai/extract", json={"url": URL, "text": "  " + "😀" * 50_000 + "\n"})
    assert res.status_code == 200  # 입력은 50,000자(코드 포인트)까지 받는다
    assert sent_body(fake.calls[0]) == "😀" * 20_000


def test_extract_pasted_text_truncated_to_20000(ai: TestClient, fake: FakeAnthropic) -> None:
    fake.add(json_reply(extract_result()))
    pasted = "".join(chr(0xAC00 + i % 100) for i in range(25_000))
    res = ai.post("/api/ai/extract", json={"url": URL, "text": pasted})
    assert res.status_code == 200
    assert res.json()["content_fetched"] is True
    assert sent_body(fake.calls[0]) == pasted[:20_000]


@pytest.mark.parametrize(
    "body",
    [
        {"url": "javascript:alert(1)"},
        {"url": "https://user:pw@x.test/"},
        {"url": URL, "text": 1},
        {"url": URL, "extra": True},
        {},
    ],
)
def test_extract_input_errors(ai: TestClient, fake: FakeAnthropic, body: dict) -> None:
    res = ai.post("/api/ai/extract", json=body)
    assert res.status_code == 400
    assert fake.calls == []


def test_extract_empty_text_means_fetch(ai: TestClient, fake: FakeAnthropic) -> None:
    server = StubServer(
        dns={"site.example.test": [PUBLIC_IP]},
        responses={PUBLIC_IP: [http_response(article())]},
    )
    use_server(ai, server)
    fake.add(json_reply(extract_result()))
    res = ai.post("/api/ai/extract", json={"url": URL, "text": "   \n "})
    assert res.status_code == 200
    assert res.json()["content_fetched"] is True
    assert len(server.connections) == 1
    content = fake.calls[0]["messages"][0]["content"]
    assert "공모전 접수는 12월 5일까지" in content
    assert "홈 메뉴" not in content  # 본문만 (메뉴 등은 빠진다)
    assert usage(ai) == {TODAY: 1}


def test_extract_fetched_text_truncated_to_20000(ai: TestClient, fake: FakeAnthropic) -> None:
    server = StubServer(
        dns={"site.example.test": [PUBLIC_IP]},
        responses={PUBLIC_IP: [http_response(article(paragraphs=600))]},
    )
    use_server(ai, server)
    fake.add(json_reply(extract_result()))
    assert ai.post("/api/ai/extract", json={"url": URL}).status_code == 200
    content = fake.calls[0]["messages"][0]["content"]
    start = content.index("\n", content.index("<page_content")) + 1
    end = content.index("\n</page_content")
    assert len(content[start:end]) == 20_000


@pytest.mark.parametrize(
    ("server", "expected_title"),
    [
        # 사설 주소로 풀리는 호스트 → 연결 없음
        (StubServer(dns={"site.example.test": ["10.0.0.1"]}), None),
        # HTML 아님
        (
            StubServer(
                dns={"site.example.test": [PUBLIC_IP]},
                responses={PUBLIC_IP: [http_response(b"%PDF", content_type="application/pdf")]},
            ),
            None,
        ),
        # 본문 200자 미만 → 미리보기 제목만
        (
            StubServer(
                dns={"site.example.test": [PUBLIC_IP]},
                responses={PUBLIC_IP: [http_response(article(paragraphs=1, title="짧은 글"))]},
            ),
            "짧은 글",
        ),
        # 가져오기 실패 (DNS 없음)
        (StubServer(), None),
    ],
)
def test_extract_without_content_skips_ai_and_counting(
    ai: TestClient, fake: FakeAnthropic, server: StubServer, expected_title: str | None
) -> None:
    use_server(ai, server)
    res = ai.post("/api/ai/extract", json={"url": URL})
    assert res.status_code == 200
    assert res.json() == {
        "title": expected_title,
        "due_date": None,
        "memo": None,
        "topic_suggestions": [],
        "content_fetched": False,
    }
    assert fake.calls == []
    assert usage(ai) == {}
    assert "10.0.0.1" not in [c.ip for c in server.connections]


def test_extract_not_fetched_is_not_counted_per_minute(ai: TestClient, fake: FakeAnthropic) -> None:
    use_server(ai, StubServer())
    for _ in range(15):
        assert ai.post("/api/ai/extract", json={"url": URL}).json()["content_fetched"] is False
    fake.add(json_reply(extract_result()))
    assert ai.post("/api/ai/extract", json={"url": URL, "text": "본문"}).status_code == 200


@pytest.mark.parametrize(
    "url",
    ["https://www.youtube.com/watch?v=abc", "https://youtu.be/abc", "https://m.youtube.com/x"],
)
def test_extract_youtube_skips_body_and_uses_oembed_title(
    ai: TestClient, fake: FakeAnthropic, url: str
) -> None:
    """유튜브는 본문을 가져오지 않는다: oEmbed 제목만 + content_fetched false."""
    oembed = json.dumps({"title": "영상 제목"}).encode()
    server = StubServer(
        dns={"www.youtube.com": [YOUTUBE_IP], "m.youtube.com": [YOUTUBE_IP]},
        responses={YOUTUBE_IP: [http_response(oembed, content_type="application/json")]},
    )
    use_server(ai, server)
    res = ai.post("/api/ai/extract", json={"url": url})
    assert res.json() == {
        "title": "영상 제목",
        "due_date": None,
        "memo": None,
        "topic_suggestions": [],
        "content_fetched": False,
    }
    (conn,) = server.connections  # oEmbed 한 번뿐 (영상 페이지 자체는 가져오지 않는다)
    assert conn.request.split(b" ", 2)[1].startswith(b"/oembed?")
    assert fake.calls == []
    assert usage(ai) == {}


def test_extract_youtube_with_pasted_text_calls_ai(ai: TestClient, fake: FakeAnthropic) -> None:
    server = StubServer()
    use_server(ai, server)
    fake.add(json_reply(extract_result()))
    res = ai.post("/api/ai/extract", json={"url": "https://youtu.be/abc", "text": "영상 설명"})
    assert res.json()["content_fetched"] is True
    assert server.dns_queries == []


def test_extract_values_cleaned(ai: TestClient, fake: FakeAnthropic) -> None:
    make_topic(ai, "Docker")
    fake.add(
        json_reply(
            {
                "title": "  제\x00목\n  줄바꿈 " + "가" * 400,
                "due_date": "2027-02-30",
                "memo": "\x00  요약\r\n- 항목\t끝\x07" + "나" * 3000,
                "topic_suggestions": [
                    "docker",
                    "DOCKER",
                    " 보안 ",
                    "x" * 31,
                    "",
                    "a",
                    "b",
                    "c",
                    "d",
                ],
            }
        )
    )
    res = ai.post("/api/ai/extract", json={"url": URL, "text": "본문"})
    data = res.json()
    assert data["title"].startswith("제목 줄바꿈 가")
    assert len(data["title"]) == 300
    assert data["due_date"] is None  # 실제 날짜가 아니다
    assert data["memo"].startswith("요약\n- 항목\t끝나")
    assert len(data["memo"]) == 2000
    assert "\x00" not in data["memo"] and "\r" not in data["memo"]
    assert data["topic_suggestions"] == ["Docker", "보안", "a", "b", "c"]


@pytest.mark.parametrize(
    ("due", "expected"),
    [("2027-01-22", "2027-01-22"), ("2027-1-22", None), ("다음 주 금요일", None), (None, None)],
)
def test_extract_due_date_rules(ai: TestClient, fake: FakeAnthropic, due, expected) -> None:
    fake.add(json_reply(extract_result(due_date=due, title="", memo="  ")))
    data = ai.post("/api/ai/extract", json={"url": URL, "text": "본문"}).json()
    assert data["due_date"] == expected
    assert data["title"] is None and data["memo"] is None


@pytest.mark.parametrize(
    "reply",
    [
        json_reply("not json"),
        json_reply([1, 2]),
        json_reply(extract_result(title=5)),
        json_reply(extract_result(topic_suggestions="공모전")),
        json_reply(extract_result(topic_suggestions=[1])),
        json_reply(extract_result(), stop="refusal"),
        json_reply(extract_result(), stop="max_tokens"),
        json_reply(extract_result(), stop="pause_turn"),
        SimpleNamespace(stop_reason="refusal", content=[]),
    ],
)
def test_extract_bad_responses_are_502(ai: TestClient, fake: FakeAnthropic, reply) -> None:
    fake.add(reply)
    res = ai.post("/api/ai/extract", json={"url": URL, "text": "본문"})
    assert res.status_code == 502
    assert res.json()["error"] == {
        "code": "ai_failed",
        "message": "AI 응답을 받지 못했어요. 잠시 후 다시 시도해 주세요.",
    }
    assert usage(ai) == {TODAY: 1}  # Claude를 불렀으므로 센다


# ── Claude 오류·재시도·사용 한도 ─────────────────────


@pytest.mark.parametrize(
    "error",
    [
        api_error(
            anthropic.RateLimitError,
            429,
            "rate_limit_error",
            "monthly cap",
            "enforced_spend_limit_reached",
        ),
        api_error(
            anthropic.BadRequestError,
            400,
            "invalid_request_error",
            "You have reached your specified API usage limits.",
        ),
        api_error(anthropic.PaymentRequiredError, 402, "billing_error", "payment required"),
        api_error(
            anthropic.BadRequestError,
            400,
            "invalid_request_error",
            "Your credit balance is too low to access the Anthropic API.",
        ),
    ],
    ids=["tier_cap", "spend_limit", "billing", "credit"],
)
def test_quota_errors_are_503_without_retry(ai: TestClient, fake: FakeAnthropic, error, caplog):
    caplog.set_level(logging.INFO)
    fake.add(error, json_reply(extract_result()))
    res = ai.post("/api/ai/extract", json={"url": URL, "text": "본문"})
    assert res.status_code == 503
    assert res.json()["error"] == {
        "code": "ai_quota_exceeded",
        "message": "이번 달 AI 사용 한도에 도달했어요.",
    }
    assert "retry-after" not in res.headers
    assert len(fake.calls) == 1  # 다시 시도하지 않는다
    assert usage(ai) == {TODAY: 1}  # 다른 실패처럼 센다
    assert error.message not in caplog.text  # 외부 오류 원문은 로그에 남기지 않는다

    fake.messages.script.clear()
    fake.add(error)
    res = ai.post("/api/ai/search", json={"query": "공모전"})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "ai_quota_exceeded"


@pytest.mark.parametrize(
    ("errors", "calls"),
    [
        ([api_error(anthropic.RateLimitError, 429, "rate_limit_error", "slow down")] * 2, 2),
        ([api_error(anthropic.InternalServerError, 500, "api_error", "boom")] * 2, 2),
        ([api_error(anthropic.OverloadedError, 529, "overloaded_error", "busy")] * 2, 2),
        ([connection_error(), connection_error()], 2),
        ([api_error(anthropic.BadRequestError, 400, "invalid_request_error", "bad param")], 1),
        ([api_error(anthropic.AuthenticationError, 401, "authentication_error", "key")], 1),
        ([api_error(anthropic.RateLimitError, 429, "rate_limit_error", "x", "other_code")] * 2, 2),
        ([RuntimeError("unexpected")], 1),
    ],
)
def test_other_errors_are_502(ai: TestClient, fake: FakeAnthropic, errors, calls) -> None:
    fake.add(*errors)
    res = ai.post("/api/ai/extract", json={"url": URL, "text": "본문"})
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "ai_failed"
    assert len(fake.calls) == calls


def test_retry_once_then_success(ai: TestClient, fake: FakeAnthropic) -> None:
    fake.add(
        api_error(anthropic.InternalServerError, 500, "api_error", "boom"),
        json_reply(extract_result()),
    )
    res = ai.post("/api/ai/extract", json={"url": URL, "text": "본문"})
    assert res.status_code == 200
    assert len(fake.calls) == 2
    assert usage(ai) == {TODAY: 1}  # 재시도는 한 요청으로 센다


def test_processing_timeout_is_502(ai: TestClient, fake: FakeAnthropic, monkeypatch) -> None:
    monkeypatch.setattr(router_module, "EXTRACT_TIMEOUT_SECONDS", 0.2)

    async def slow(_: dict[str, Any]) -> Any:
        await asyncio.sleep(5)

    fake.add(slow)
    res = ai.post("/api/ai/extract", json={"url": URL, "text": "본문"})
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "ai_failed"
    # 동시 처리 자리를 돌려줬다
    assert ai.app.state.ai_limiter._active == 0


# ── AI 검색 ─────────────────────────────────────────


@pytest.fixture
def scraps(ai: TestClient) -> dict[str, int]:
    tid = make_topic(ai, "대회")
    return {
        "contest": make_scrap(ai, "대학생 공모전", memo="상금 " + "가" * 400, topic_ids=[tid]),
        "hackathon": make_scrap(ai, "해커톤 대회", memo="contest", due_date="2027-01-20"),
        "recipe": make_scrap(ai, "김치찌개 레시피"),
    }


def test_search_tool_loop(ai: TestClient, fake: FakeAnthropic, scraps: dict[str, int]) -> None:
    fake.add(
        tool_reply("공모전"),
        tool_reply("대회", "contest"),
        json_reply(
            {
                "answer": "  공모전 관련 스크랩 2개를 찾았어요.\n",
                "results": [
                    {"id": scraps["hackathon"], "reason": " 해커톤 \n 대회라서 " + "x" * 300},
                    {"id": scraps["contest"], "reason": "공모전"},
                    {"id": scraps["contest"], "reason": "중복"},
                    {"id": 999_999, "reason": "지어낸 id"},
                    {"id": scraps["recipe"], "reason": "도구 결과에 없던 id"},
                ],
            }
        ),
    )
    res = ai.post("/api/ai/search", json={"query": " 공모전 찾아줘 "})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["answer"] == "공모전 관련 스크랩 2개를 찾았어요."
    assert [r["scrap"]["id"] for r in data["results"]] == [scraps["hackathon"], scraps["contest"]]
    assert data["results"][0]["reason"].startswith("해커톤 대회라서 x")
    assert len(data["results"][0]["reason"]) == 200
    # ScrapListItem 형식 (목록 응답과 같다)
    listed = {i["id"]: i for i in ai.get("/api/scraps").json()["items"]}
    for r in data["results"]:
        assert r["scrap"] == listed[r["scrap"]["id"]]
        assert "memo" not in r["scrap"] and "memo_preview" in r["scrap"]

    assert len(fake.calls) == 3
    first, second, third = fake.calls
    assert first["tools"][0]["name"] == "search_scraps" and first["tools"][0]["strict"] is True
    assert first["tools"] == second["tools"] == third["tools"]  # 도구 목록은 바뀌지 않는다
    assert first["system"] == third["system"]
    assert first["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": SEARCH_SCHEMA},
    }
    assert first["cache_control"] == {"type": "ephemeral"}
    assert first["betas"] == [FALLBACK_BETA] and first["fallbacks"] == "default"
    assert "tool_choice" not in first
    assert 0 < first["timeout"] <= 90
    assert first["messages"] == [
        {"role": "user", "content": f"오늘 날짜(Asia/Seoul): {TODAY}\n질문: 공모전 찾아줘"}
    ]
    # 2회차: 응답(thinking 포함)을 그대로 돌려주고, 도구 결과를 붙인다
    assistant, tool_results = second["messages"][1:]
    assert assistant["role"] == "assistant" and assistant["content"][0].type == "thinking"
    (result,) = tool_results["content"]
    assert result["tool_use_id"] == "toolu_0_공모전" and "is_error" not in result
    payload = json.loads(result["content"])
    assert [c["id"] for c in payload["scraps"]] == [scraps["contest"]]
    candidate = payload["scraps"][0]
    assert set(candidate) == {
        "id",
        "title",
        "url",
        "source",
        "topics",
        "due_date",
        "memo_preview",
        "liked",
    }
    assert candidate["topics"] == ["대회"] and len(candidate["memo_preview"]) == 300
    # 3회차: 병렬 도구 호출 두 개의 결과
    results = third["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["toolu_0_대회", "toolu_1_contest"]
    assert usage(ai) == {TODAY: 1}  # 회차와 상관없이 요청 하나로 센다


def test_search_tool_call_limit(ai: TestClient, fake: FakeAnthropic, scraps, monkeypatch) -> None:
    executed: list[object] = []
    real = router_module._run_search_tool

    def spy(database, tool_input):
        executed.append(tool_input)
        return real(database, tool_input)

    monkeypatch.setattr(router_module, "_run_search_tool", spy)
    fake.add(
        *[tool_reply(f"q{i}") for i in range(4)],
        tool_reply("q4", "q5", "q6"),  # 6번째까지만 실행, 7번째는 오류 결과
        tool_reply("q7"),
        json_reply({"answer": "없어요", "results": []}),
    )
    res = ai.post("/api/ai/search", json={"query": "아무거나"})
    assert res.status_code == 200
    assert len(executed) == MAX_TOOL_CALLS
    over = fake.calls[5]["messages"][-1]["content"]
    assert [r.get("is_error", False) for r in over if r["type"] == "tool_result"] == [
        False,
        False,
        True,
    ]
    assert over[-1] == {"type": "text", "text": TOOL_LIMIT_NOTICE}
    last = fake.calls[6]["messages"][-1]["content"]
    assert last[0]["is_error"] is True
    assert res.json() == {"answer": "없어요", "results": []}


def test_search_endless_tool_use_fails(ai: TestClient, fake: FakeAnthropic, scraps) -> None:
    fake.add(*[tool_reply(f"q{i}") for i in range(20)])
    res = ai.post("/api/ai/search", json={"query": "아무거나"})
    assert res.status_code == 502
    assert len(fake.calls) == MAX_TOOL_CALLS + 2


def test_search_unknown_tool_and_bad_query(ai: TestClient, fake: FakeAnthropic, scraps) -> None:
    fake.add(
        tool_reply("x", name="delete_everything"),
        tool_reply("a\x00b"),
        json_reply(
            {"answer": "못 찾았어요", "results": [{"id": scraps["contest"], "reason": "r"}]}
        ),
    )
    res = ai.post("/api/ai/search", json={"query": "q"})
    assert res.status_code == 200
    second = fake.calls[1]["messages"][-1]["content"][0]
    third = fake.calls[2]["messages"][-1]["content"][0]
    assert second["is_error"] is True and third["is_error"] is True
    # 도구 결과에 나온 적 없는 id → 빠지고 "못 찾음" 문장
    assert res.json() == {"answer": "관련 스크랩을 찾지 못했어요.", "results": []}


def test_search_excludes_deleted_scrap(ai: TestClient, fake: FakeAnthropic, scraps) -> None:
    def delete_then_answer(_: dict[str, Any]) -> SimpleNamespace:
        assert ai.delete(f"/api/scraps/{scraps['contest']}").status_code == 204
        return json_reply(
            {
                "answer": "2개",
                "results": [
                    {"id": scraps["contest"], "reason": "지워짐"},
                    {"id": scraps["hackathon"], "reason": "남음"},
                ],
            }
        )

    fake.add(tool_reply("대회"), delete_then_answer)
    res = ai.post("/api/ai/search", json={"query": "대회"})
    assert [r["scrap"]["id"] for r in res.json()["results"]] == [scraps["hackathon"]]


def test_search_results_capped_at_10(ai: TestClient, fake: FakeAnthropic) -> None:
    ids = [make_scrap(ai, f"공모 {i}") for i in range(15)]
    fake.add(
        tool_reply("공모"),
        json_reply({"answer": "많아요", "results": [{"id": i, "reason": "r"} for i in ids]}),
    )
    data = ai.post("/api/ai/search", json={"query": "공모"}).json()
    assert [r["scrap"]["id"] for r in data["results"]] == ids[:10]


@pytest.mark.parametrize(
    "reply",
    [
        json_reply({"answer": "x"}),
        json_reply({"answer": "x", "results": [{"id": "1", "reason": "r"}]}),
        json_reply({"answer": "x", "results": [{"id": True, "reason": "r"}]}),
        json_reply({"answer": 1, "results": []}),
        json_reply({"answer": "x", "results": []}, stop="refusal"),
        json_reply({"answer": "x", "results": []}, stop="max_tokens"),
        SimpleNamespace(stop_reason="tool_use", content=[block("text", text="?")]),
    ],
)
def test_search_bad_responses_are_502(ai: TestClient, fake: FakeAnthropic, reply) -> None:
    fake.add(reply)
    res = ai.post("/api/ai/search", json={"query": "공모전"})
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "ai_failed"


def test_search_refusal_mid_loop(ai: TestClient, fake: FakeAnthropic, scraps) -> None:
    fake.add(tool_reply("공모전"), json_reply({}, stop="refusal"))
    assert ai.post("/api/ai/search", json={"query": "공모전"}).status_code == 502


@pytest.mark.parametrize(
    "body", [{"query": ""}, {"query": "가" * 201}, {"query": "a\nb"}, {"query": 1}, {"q": "x"}]
)
def test_search_input_rules(ai: TestClient, fake: FakeAnthropic, body: dict) -> None:
    res = ai.post("/api/ai/search", json=body)
    assert res.status_code == 400
    assert fake.calls == []
    assert usage(ai) == {}


def test_search_empty_answer_default(ai: TestClient, fake: FakeAnthropic, scraps) -> None:
    fake.add(
        tool_reply("대회"),
        json_reply({"answer": " ", "results": [{"id": scraps["hackathon"], "reason": "r"}]}),
    )
    assert ai.post("/api/ai/search", json={"query": "대회"}).json()["answer"] == (
        "관련 스크랩 1개를 찾았어요."
    )


# ── AI 요청 제한 ────────────────────────────────────


def ok_extract(client: TestClient, fake: FakeAnthropic) -> Any:
    fake.add(json_reply(extract_result()))
    return client.post("/api/ai/extract", json={"url": URL, "text": "본문"})


def test_per_minute_limit(ai: TestClient, fake: FakeAnthropic, clock: FakeClock) -> None:
    for _ in range(10):
        assert ok_extract(ai, fake).status_code == 200
    fake.messages.script.clear()
    res = ai.post("/api/ai/search", json={"query": "x"})  # 두 엔드포인트 합산
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "too_many_requests"
    assert 1 <= int(res.headers["retry-after"]) <= 60
    assert len(fake.calls) == 10
    # 입력 오류는 제한보다 먼저 (그리고 세지 않는다)
    assert ai.post("/api/ai/search", json={"query": ""}).status_code == 400
    # 다른 API 에는 영향 없음
    assert ai.get("/api/scraps").status_code == 200
    clock.advance(61)
    assert ok_extract(ai, fake).status_code == 200


def test_per_day_limit_persists(make_client, clock: FakeClock, tmp_path, monkeypatch) -> None:
    from tests.conftest import do_login, do_setup

    db = str(tmp_path / "day.db")
    env = {"DB_PATH": db, "ANTHROPIC_API_KEY": FAKE_KEY, "AI_PER_DAY": "3", "AI_PER_MINUTE": "100"}
    client = make_client(clock=clock, **env)
    secret, _ = do_setup(client, clock)
    fake = FakeAnthropic()
    install(client, fake)
    for _ in range(3):
        assert ok_extract(client, fake).status_code == 200
    fake.messages.script.clear()
    res = client.post("/api/ai/extract", json={"url": URL, "text": "본문"})
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "ai_daily_limit"  # v1.6
    # 다음 날(Asia/Seoul 자정)까지 남은 초.
    # FakeClock 은 17:00 에서 시작하고 do_setup 이 30초 넘긴다.
    assert int(res.headers["retry-after"]) == SECONDS_TO_MIDNIGHT - 30

    # 재시작(새 앱, 같은 DB) 뒤에도 하루 횟수가 이어진다.
    restarted = make_client(clock=clock, **env)
    do_login(restarted, clock, secret)
    install(restarted, fake)
    assert restarted.post("/api/ai/search", json={"query": "x"}).status_code == 429
    assert usage(restarted) == {TODAY: 3}

    clock.advance(SECONDS_TO_MIDNIGHT)  # 다음 날 (Asia/Seoul)
    assert ok_extract(restarted, fake).status_code == 200
    assert usage(restarted) == {TODAY: 3, "2027-01-16": 1}


def test_concurrency_limit(ai: TestClient, fake: FakeAnthropic) -> None:
    limiter = ai.app.state.ai_limiter
    held = [limiter.begin(), limiter.begin()]
    res = ai.post("/api/ai/extract", json={"url": URL, "text": "본문"})
    assert res.status_code == 429
    assert res.headers["retry-after"] == "5"
    for ticket in held:
        limiter.finish(ticket)
    assert ok_extract(ai, fake).status_code == 200
    assert usage(ai) == {TODAY: 1}  # 예약만 하고 끝난 것은 세지 않는다


def test_concurrent_reservations_count_toward_minute_limit(ai: TestClient) -> None:
    limiter = ai.app.state.ai_limiter
    limiter.max_concurrent = 100
    tickets = [limiter.begin() for _ in range(10)]
    res = ai.post("/api/ai/search", json={"query": "x"})
    assert res.status_code == 429
    for ticket in tickets:
        limiter.finish(ticket)


def test_unavailable_not_counted(make_client, clock, tmp_path) -> None:
    from tests.conftest import do_setup

    client = make_client(clock=clock, DB_PATH=str(tmp_path / "t.db"), AI_PER_MINUTE="1")
    do_setup(client, clock)
    for _ in range(3):
        assert client.post("/api/ai/search", json={"query": "x"}).status_code == 503
    fake = FakeAnthropic()
    install(client, fake)
    assert ok_extract(client, fake).status_code == 200


# ── 마이그레이션 (추가 위주) ─────────────────────────


def test_rollback_to_code_without_0004(make_client, clock, tmp_path, monkeypatch) -> None:
    """0004(ai_usage_days)가 적용된 DB를 0003까지만 아는 코드로 열어도 동작한다."""
    from functools import partial

    import app.db as db_module
    from app.db import apply_migrations, list_migrations
    from tests.conftest import do_setup

    db_path = str(tmp_path / "rollback.db")
    new = make_client(clock=clock, DB_PATH=db_path)
    assert new.get("/api/health").status_code == 200
    older = tmp_path / "older"
    older.mkdir()
    for _, name, path in list_migrations():
        if name < "0004":
            (older / name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(db_module, "apply_migrations", partial(apply_migrations, directory=older))
    old = make_client(clock=clock, DB_PATH=db_path)
    do_setup(old, clock)
    assert old.post("/api/scraps", json={"url": "https://ex.test/"}).status_code == 201
    assert old.get("/api/scraps?q=ex.test").json()["items"]


# ── 실제 SDK 요청 형식 (네트워크 없이 가짜 전송 계층) ────────


def test_real_sdk_request_shape(ai: TestClient, scraps) -> None:
    """실제 `anthropic` SDK로 요청을 만들어 본다. 전송 계층만 가짜라 외부로 나가지 않는다."""
    sent: list[httpx2.Request] = []
    replies = [
        {
            "stop_reason": "tool_use",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "sig1"},
                {
                    "type": "tool_use",
                    "id": "toolu_01",
                    "name": "search_scraps",
                    "input": {"query": "대회"},
                },
            ],
        },
        {
            "stop_reason": "end_turn",
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"answer": "1개", "results": [{"id": scraps["hackathon"], "reason": "r"}]}
                    ),
                }
            ],
        },
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        reply = replies[len(sent) - 1]
        body = {
            "id": f"msg_{len(sent)}",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
            **reply,
        }
        return httpx2.Response(200, json=body, headers={"request-id": "req_test"})

    def factory(key: str) -> anthropic.AsyncAnthropic:
        return anthropic.AsyncAnthropic(
            api_key=key,
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        )

    ai.app.state.ai_gateway = ClaudeGateway(FAKE_KEY, "claude-opus-5-5", client_factory=factory)
    res = ai.post("/api/ai/search", json={"query": "대회"})
    assert res.status_code == 200, res.text
    assert [r["scrap"]["id"] for r in res.json()["results"]] == [scraps["hackathon"]]

    first, second = sent
    assert first.url.path == "/v1/messages"
    assert FALLBACK_BETA in first.headers["anthropic-beta"]
    payload = json.loads(first.content)
    assert payload["model"] == "claude-opus-5-5"
    assert payload["fallbacks"] == "default"
    assert payload["output_config"]["effort"] == "medium"
    assert payload["tools"][0]["strict"] is True
    assert "thinking" not in payload and "temperature" not in payload
    assert "betas" not in payload  # 헤더로만 간다
    # 2회차: thinking 블록(서명 포함)과 tool_use 를 그대로 돌려보냈다
    echoed = json.loads(second.content)["messages"][1]["content"]
    assert echoed[0] == {"type": "thinking", "thinking": "", "signature": "sig1"}
    assert echoed[1]["type"] == "tool_use" and echoed[1]["id"] == "toolu_01"


# ── 리뷰 후속: 출력 정리·도구 결과 축소·가져오기 제한·연결 끊김·fallbacks 설정 ──

BIDI = "‮⁦‏؜‪⁩‎"


def test_bidi_chars_removed_from_ai_output(ai: TestClient, fake: FakeAnthropic, scraps) -> None:
    fake.add(
        json_reply(
            extract_result(
                title=f"제{BIDI}목",
                memo=f"[{BIDI}elpmaxe.doog//:sptth](https://evil.example)\n- 항목",
                topic_suggestions=[f"보{BIDI}안"],
            )
        )
    )
    data = ai.post("/api/ai/extract", json={"url": URL, "text": "본문"}).json()
    assert data["title"] == "제목"
    # 방향 문자를 지운 뒤 링크 정리(v1.6)까지: 링크는 글자 + 실제 호스트로 남는다.
    assert data["memo"] == "elpmaxe.doog//:sptth (evil.example)\n- 항목"
    assert data["topic_suggestions"] == ["보안"]

    fake.add(
        tool_reply("대회"),
        json_reply(
            {
                "answer": f"찾{BIDI}았어요",
                "results": [{"id": scraps["hackathon"], "reason": f"이{BIDI}유"}],
            }
        ),
    )
    data = ai.post("/api/ai/search", json={"query": "대회"}).json()
    assert data["answer"] == "찾았어요"
    assert data["results"][0]["reason"] == "이유"


def test_tool_results_are_shortened(ai: TestClient, fake: FakeAnthropic) -> None:
    topic_ids = [make_topic(ai, f"주제{i}") for i in range(7)]
    res = ai.post(
        "/api/scraps",
        json={
            "url": "https://u:p@ex.test:8443/path/" + "a" * 300 + "?token=secret#frag",
            "title": "공모 " + "가" * 290,
            "memo": "메" * 500,
            "topic_ids": topic_ids,
        },
    )
    assert res.status_code == 400  # 사용자 정보가 든 URL은 저장 자체가 안 된다
    res = ai.post(
        "/api/scraps",
        json={
            "url": "https://ex.test:8443/path/" + "a" * 300 + "?token=secret#frag",
            "title": "공모 " + "가" * 290,
            "memo": "메" * 500,
            "topic_ids": topic_ids,
        },
    )
    sid = res.json()["id"]
    fake.add(
        tool_reply("공모"),
        json_reply({"answer": "1개", "results": [{"id": sid, "reason": "r"}]}),
    )
    data = ai.post("/api/ai/search", json={"query": "공모"}).json()
    (candidate,) = json.loads(fake.calls[1]["messages"][-1]["content"][0]["content"])["scraps"]
    assert candidate["url"] == ("https://ex.test:8443/path/" + "a" * 300)[:200]
    assert "token" not in candidate["url"] and "frag" not in candidate["url"]
    assert len(candidate["title"]) == 150
    assert candidate["topics"] == [f"주제{i}" for i in range(5)]
    assert len(candidate["memo_preview"]) == 300
    # 화면에는 DB에서 다시 읽은 전체 값
    (result,) = data["results"]
    assert result["scrap"]["url"].endswith("?token=secret#frag")
    assert len(result["scrap"]["topics"]) == 7


def test_max_tokens_per_endpoint(ai: TestClient, fake: FakeAnthropic) -> None:
    fake.add(json_reply(extract_result()))
    ai.post("/api/ai/extract", json={"url": URL, "text": "본문"})
    fake.add(json_reply({"answer": "x", "results": []}))
    ai.post("/api/ai/search", json={"query": "x"})
    assert [c["max_tokens"] for c in fake.calls] == [
        router_module.EXTRACT_MAX_TOKENS,
        router_module.SEARCH_MAX_TOKENS,
    ]
    assert router_module.EXTRACT_MAX_TOKENS <= 8_192
    assert router_module.SEARCH_MAX_TOKENS <= 8_192


def test_fetch_limit_shared_with_preview(ai: TestClient, fake: FakeAnthropic, clock) -> None:
    server = StubServer()  # 모두 가져오기 실패 → 본문 없음
    use_server(ai, server)
    for _ in range(10):
        assert ai.post("/api/meta/preview", json={"url": URL}).status_code == 200
    for _ in range(10):
        res = ai.post("/api/ai/extract", json={"url": URL})
        assert res.json()["content_fetched"] is False  # 본문 없음도 센다
    res = ai.post("/api/ai/extract", json={"url": URL})
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "too_many_requests"
    assert 1 <= int(res.headers["retry-after"]) <= 60
    assert ai.post("/api/meta/preview", json={"url": URL}).status_code == 429
    # 붙여넣은 본문은 가져오지 않으므로 이 상한과 상관없다
    fake.add(json_reply(extract_result()))
    assert ai.post("/api/ai/extract", json={"url": URL, "text": "본문"}).status_code == 200
    assert usage(ai) == {TODAY: 1}
    clock.advance(61)
    assert ai.post("/api/ai/extract", json={"url": URL}).status_code == 200


def test_disconnect_stops_search_between_rounds(
    ai: TestClient, fake: FakeAnthropic, scraps, monkeypatch
) -> None:
    from starlette.requests import Request

    checks = {"n": 0}

    async def disconnected_after_first(self) -> bool:
        checks["n"] += 1
        return checks["n"] > 1

    monkeypatch.setattr(Request, "is_disconnected", disconnected_after_first)
    fake.add(tool_reply("대회"), json_reply({"answer": "x", "results": []}))
    res = ai.post("/api/ai/search", json={"query": "대회"})
    assert res.status_code == 499
    assert len(fake.calls) == 1  # 2회차 호출 전에 멈췄다
    assert usage(ai) == {TODAY: 1}  # 이미 센 횟수는 그대로
    assert ai.app.state.ai_limiter._active == 0


def test_disconnect_stops_extract_before_claude(
    ai: TestClient, fake: FakeAnthropic, monkeypatch
) -> None:
    from starlette.requests import Request

    async def always(self) -> bool:
        return True

    monkeypatch.setattr(Request, "is_disconnected", always)
    fake.add(json_reply(extract_result()))
    res = ai.post("/api/ai/extract", json={"url": URL, "text": "본문"})
    assert res.status_code == 499
    assert fake.calls == []


def test_fallbacks_can_be_disabled(make_client, clock, tmp_path) -> None:
    from tests.conftest import do_setup

    client = make_client(
        clock=clock,
        DB_PATH=str(tmp_path / "t.db"),
        ANTHROPIC_API_KEY=FAKE_KEY,
        ANTHROPIC_FALLBACKS="0",
    )
    assert client.app.state.settings.anthropic_fallbacks is False
    gateway: ClaudeGateway = client.app.state.ai_gateway
    assert gateway.fallbacks is False
    do_setup(client, clock)
    fake = FakeAnthropic([json_reply(extract_result())])
    gateway._factory = lambda key: fake
    assert client.post("/api/ai/extract", json={"url": URL, "text": "본문"}).status_code == 200
    (call,) = fake.calls
    assert "betas" not in call and "fallbacks" not in call

    on = make_client(clock=clock, DB_PATH=str(tmp_path / "u.db"), ANTHROPIC_FALLBACKS="no")
    assert on.app.state.settings.anthropic_fallbacks is True  # 정확히 "0"일 때만 끈다


# ── 메모 링크 정리 (v1.6, 규칙별 단위 테스트는 tests/test_memolinks.py) ──


def test_extract_endpoint_cleans_memo_links(ai: TestClient, fake: FakeAnthropic) -> None:
    fake.add(
        json_reply(
            extract_result(
                title="[제목](https://t.test)",
                memo="- [신청](https://apply.example.test/form)\n- ![](https://img.test/a.png)\n"
                "- https://bare.example.test\n\n[r]: https://ref.test",
            )
        )
    )
    data = ai.post("/api/ai/extract", json={"url": URL, "text": "본문"}).json()
    assert data["memo"] == "- 신청 (apply.example.test)\n- \n- https://bare.example.test"
    assert data["title"] == "[제목](https://t.test)"  # 메모에만 적용한다


def test_user_memo_is_not_cleaned(ai: TestClient) -> None:
    memo = "[직접 쓴 링크](https://mine.test)"
    res = ai.post("/api/scraps", json={"url": "https://ex.test/u", "memo": memo})
    assert res.status_code == 201, res.text
    assert ai.get(f"/api/scraps/{res.json()['id']}").json()["memo"] == memo
