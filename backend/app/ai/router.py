"""AI API `/api/ai` (docs/API.md v1.5·v1.6 "AI 세부 규칙").

세션 필수 상위 라우터(app/routing.py) 아래에 붙는다. AI가 돌려준 값은 저장하지 않는다.

오류 판정 순서: (미들웨어) 공통 429 → 403 → 401 → 413 → (여기) 입력 오류 400 → AI 사용 불가 503
`ai_unavailable` → AI 요청 제한 429(분·하루 횟수·하루 토큰 예산·동시 처리) → 처리.
처리 중 실패는 502 `ai_failed`, 사용 한도·결제 문제는 503 `ai_quota_exceeded`(Retry-After 없음).
AI 검색은 매 Claude 호출 직전에도 하루 토큰 예산을 확인한다(넘으면 429).

로그에는 키·본문·검색어·URL을 남기지 않는다.
"""

import asyncio
import json
import logging
import re
import sqlite3
import time
import unicodedata
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from app.ai.claude import (
    AiFailed,
    AiQuotaExceeded,
    ClaudeGateway,
    blocks,
    check_stop_reason,
    response_json,
)
from app.ai.limits import (
    AiDailyLimitExceeded,
    AiLimitExceeded,
    AiRequestLimiter,
    AiTicket,
    AiTokenBudgetExceeded,
    kst_day,
    response_tokens,
)
from app.ai.memolinks import strip_memo_links
from app.ai.prompts import (
    EXTRACT_SCHEMA,
    EXTRACT_SYSTEM,
    MAX_TOOL_CALLS,
    SEARCH_SCHEMA,
    SEARCH_SYSTEM,
    SEARCH_TOOL,
    TOOL_LIMIT_NOTICE,
    extract_user_message,
    search_user_message,
)
from app.clock import Clock
from app.db import Database, DatabaseUnavailableError
from app.errors import ApiError
from app.pagetext import PageTextFetcher
from app.preview import PreviewFetcher, clean_title, is_youtube_host
from app.ratelimit import RequestRateLimiter, client_key
from app.scraps import list_items_by_id, search_list_items
from app.search import parse_query
from app.validation import StrictBody, invalid_input, url_host, validate_url

router = APIRouter(prefix="/ai")
logger = logging.getLogger("app")

EXTRACT_TIMEOUT_SECONDS = 60.0
SEARCH_TIMEOUT_SECONDS = 90.0
PASTED_TEXT_MAX_CHARS = 50_000
FETCHED_TEXT_MAX_CHARS = 20_000  # AI에 보내는 본문 상한 (가져온 것·붙여넣은 것 공통)
QUERY_MAX_CHARS = 200
MEMO_MAX_CHARS = 2_000
TOPIC_SUGGESTIONS_MAX = 5
TOPIC_NAME_MAX_CHARS = 30
SEARCH_TOOL_LIMIT = 20
# 도구 결과 후보의 길이 상한 (토큰·외부로 나가는 정보를 줄인다).
# 화면에는 DB에서 다시 읽은 전체 값이 나간다.
TOOL_URL_MAX_CHARS = 200
TOOL_TITLE_MAX_CHARS = 150
TOOL_TOPICS_MAX = 5
# 응답 길이 상한 (thinking 포함). 답 JSON은 짧다:
# - 채우기: 메모 2,000자 + 제목 300자 JSON 이 한국어로 약 2~3천 토큰.
#   낮은 effort 의 thinking 여유를 더해 6,144.
# - 검색: 회차마다 도구 호출 또는 답(요약 500자 + 이유 200자×10).
#   중간 effort thinking 여유를 더해 8,192.
# 도달하면 `max_tokens` 종료 → 502.
EXTRACT_MAX_TOKENS = 6_144
SEARCH_MAX_TOKENS = 8_192
SEARCH_RESULTS_MAX = 10
REASON_MAX_CHARS = 200
ANSWER_MAX_CHARS = 500
# 도구 호출 상한을 넘긴 뒤에도 도구만 부르면 몇 번 더 기회를 주고 실패로 끝낸다.
MAX_ROUNDS = MAX_TOOL_CALLS + 2
NOT_FOUND_ANSWER = "관련 스크랩을 찾지 못했어요."
_RAW_TEXT_MAX = 1_000_000
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# 글자 방향 서식 문자 (AI 출력에서 지운다).
_BIDI_CHARS = frozenset(
    "\u061c\u200e\u200f"
    + "".join(map(chr, range(0x202A, 0x202F)))
    + "".join(map(chr, range(0x2066, 0x206A)))
)


class ExtractBody(StrictBody):
    url: str = Field(max_length=_RAW_TEXT_MAX)
    text: str | None = Field(default=None, max_length=_RAW_TEXT_MAX)


class SearchBody(StrictBody):
    query: str = Field(max_length=_RAW_TEXT_MAX)


# ── 오류 ────────────────────────────────────────────


def _ai_failed() -> ApiError:
    return ApiError(502, "ai_failed", "AI 응답을 받지 못했어요. 잠시 후 다시 시도해 주세요.")


def _too_many(retry_after: int) -> ApiError:
    return ApiError(
        429,
        "too_many_requests",
        "AI 요청이 너무 많아요. 잠시 후 다시 시도해 주세요.",
        headers={"Retry-After": str(retry_after)},
    )


def _daily_limit_reached(retry_after: int) -> ApiError:
    # 하루 요청 횟수 (docs/API.md v1.6). Retry-After 는 다음 Asia/Seoul 자정까지 (최소 1초).
    return ApiError(
        429,
        "ai_daily_limit",
        "오늘 AI 요청 횟수를 모두 썼어요. 내일 다시 시도해 주세요.",
        headers={"Retry-After": str(retry_after)},
    )


def _token_budget_exhausted(retry_after: int) -> ApiError:
    # 하루 토큰 예산 (docs/API.md v1.6). Retry-After 는 다음 Asia/Seoul 자정까지 (최소 1초).
    return ApiError(
        429,
        "ai_daily_limit",
        "오늘 AI 사용량을 모두 썼어요. 내일 다시 시도해 주세요.",
        headers={"Retry-After": str(retry_after)},
    )


def _ai_quota() -> ApiError:
    # 언제 풀릴지 서버가 알 수 없으므로 Retry-After 를 넣지 않는다.
    return ApiError(503, "ai_quota_exceeded", "이번 달 AI 사용 한도에 도달했어요.")


class ClientGone(Exception):
    """클라이언트 연결이 끊김 → 다음 Claude 호출 전에 멈춘다."""


async def _stop_if_disconnected(request: Request) -> None:
    if await request.is_disconnected():
        logger.info("클라이언트 연결이 끊겨 AI 처리를 멈춥니다.")
        raise ClientGone


def _check_fetch_limit(request: Request) -> None:
    """서버가 사용자 URL을 가져오는 요청의 IP별 분당 상한 (`/meta/preview`와 합산)."""
    limiter: RequestRateLimiter = request.app.state.fetch_limiter
    retry_after = limiter.hit(client_key(request.client.host if request.client else None))
    if retry_after is not None:
        raise ApiError(
            429,
            "too_many_requests",
            "외부 페이지 가져오기 요청이 너무 많아요. 잠시 후 다시 시도해 주세요.",
            headers={"Retry-After": str(retry_after)},
        )


def _db_unavailable() -> ApiError:
    return ApiError(503, "db_unavailable", "데이터베이스에 연결할 수 없습니다.")


# ── 입력 검사 ────────────────────────────────────────


def _clean_pasted_text(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    if len(text) > PASTED_TEXT_MAX_CHARS:
        raise invalid_input(f"붙여넣은 본문은 {PASTED_TEXT_MAX_CHARS:,}자 이하로 넣어 주세요.")
    if any(unicodedata.category(ch) == "Cc" and ch not in "\n\r\t" for ch in text):
        raise invalid_input("붙여넣은 본문에 사용할 수 없는 문자가 있습니다.")
    return text


def _clean_query(raw: str) -> str:
    query = unicodedata.normalize("NFC", raw.strip())
    if not query or len(query) > QUERY_MAX_CHARS:
        raise invalid_input(f"질문은 1~{QUERY_MAX_CHARS}자로 입력해 주세요.")
    if any(unicodedata.category(ch) == "Cc" for ch in query):
        raise invalid_input("질문에 사용할 수 없는 문자가 있습니다.")
    return query


# ── 공통 흐름 ────────────────────────────────────────


def _gateway(request: Request) -> ClaudeGateway:
    gateway: ClaudeGateway = request.app.state.ai_gateway
    if not gateway.available:
        raise ApiError(503, "ai_unavailable", "AI 기능을 사용할 수 없어요 (서버 설정 필요)")
    return gateway


async def _begin(limiter: AiRequestLimiter) -> AiTicket:
    try:
        return await run_in_threadpool(limiter.begin)
    except AiTokenBudgetExceeded as exc:
        raise _token_budget_exhausted(exc.retry_after) from None
    except AiDailyLimitExceeded as exc:
        raise _daily_limit_reached(exc.retry_after) from None
    except AiLimitExceeded as exc:
        # 분당 횟수·동시 처리
        raise _too_many(exc.retry_after) from None
    except DatabaseUnavailableError as exc:
        logger.error("AI 요청 제한 확인 실패: %s", type(exc).__name__)
        raise _db_unavailable() from None


async def _commit(limiter: AiRequestLimiter, ticket: AiTicket) -> None:
    try:
        await run_in_threadpool(limiter.commit, ticket)
    except (DatabaseUnavailableError, sqlite3.Error) as exc:
        logger.error("AI 요청 횟수 기록 실패: %s", type(exc).__name__)
        raise _db_unavailable() from None


async def _check_tokens(limiter: AiRequestLimiter) -> None:
    """AI 검색의 매 Claude 호출 직전: 하루 토큰 예산 확인 (넘었으면 `AiTokenBudgetExceeded`)."""
    try:
        await run_in_threadpool(limiter.check_tokens)
    except (DatabaseUnavailableError, sqlite3.Error) as exc:
        logger.error("AI 토큰 사용량 확인 실패: %s", type(exc).__name__)
        raise _db_unavailable() from None


async def _create(
    gateway: ClaudeGateway,
    limiter: AiRequestLimiter,
    params: dict[str, Any],
    deadline: float,
) -> Any:
    """Claude 호출 → 응답의 사용량을 바로 누적한다.

    응답이 왔으면 내용(거부·형식 위반 등)과 상관없이 먼저 누적한다
    (실패한 호출도 usage가 있으면 센다).
    """
    response = await gateway.create(params, deadline)
    try:
        await run_in_threadpool(limiter.add_tokens, response_tokens(response))
    except (DatabaseUnavailableError, sqlite3.Error) as exc:
        logger.error("AI 토큰 사용량 기록 실패: %s", type(exc).__name__)
        raise _db_unavailable() from None
    return response


async def _run(request: Request, timeout: float, work: Any) -> dict[str, object]:
    """사용 가능 확인 → 요청 제한 → `work(gateway, ticket, deadline)`를 시간 상한 안에서."""
    gateway = _gateway(request)
    limiter: AiRequestLimiter = request.app.state.ai_limiter
    ticket = await _begin(limiter)
    deadline = time.monotonic() + timeout
    try:
        async with asyncio.timeout(timeout):
            return await work(gateway, ticket, deadline)
    except TimeoutError:
        logger.warning("AI 처리 시간 초과")
        raise _ai_failed() from None
    except AiFailed:
        raise _ai_failed() from None
    except AiQuotaExceeded:
        raise _ai_quota() from None
    except AiTokenBudgetExceeded as exc:
        raise _token_budget_exhausted(exc.retry_after) from None
    except ClientGone:
        # 응답을 받을 쪽이 없다. 이미 센 횟수는 되돌리지 않는다.
        raise ApiError(499, "client_closed", "요청이 취소되었습니다.") from None
    except DatabaseUnavailableError as exc:
        logger.error("AI 처리 중 DB 사용 불가: %s", type(exc).__name__)
        raise _db_unavailable() from None
    finally:
        limiter.finish(ticket)


def _today(request: Request) -> str:
    clock: Clock = request.app.state.clock
    return kst_day(clock.now())


def _with_conn[T](database: Database, fn: Any, *args: object) -> T:
    conn = database.connect()
    try:
        return fn(conn, *args)
    finally:
        conn.close()


# ── 값 정리 ─────────────────────────────────────────


def _strip_bidi(value: str) -> str:
    return "".join(ch for ch in value if ch not in _BIDI_CHARS)


def _clean_line(value: str, limit: int) -> str:
    """한 줄 문자열: 공백을 하나로, 제어문자·글자 방향 서식 문자 제거, 최대 `limit`자."""
    text = " ".join(_strip_bidi(value).split())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cc")
    return text.strip()[:limit].strip()


def _clean_due_date(value: str | None) -> str | None:
    if value is None or not _DATE.match(value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _clean_memo(value: str | None) -> str | None:
    """제어문자·글자 방향 서식 문자 제거 → 링크 정리(v1.6) → 2,000자 자르기.

    링크 정리는 남은 `[`·`]`를 모두 이스케이프하므로, 자른 끝이 새 링크 문법이 될 수 없다.
    """
    if value is None:
        return None
    text = _strip_bidi(value.replace("\r\n", "\n"))
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) != "Cc")
    text = strip_memo_links(text.strip())
    text = text.strip()[:MEMO_MAX_CHARS].rstrip()
    if (len(text) - len(text.rstrip("\\"))) % 2:
        text = text[:-1].rstrip()  # 자르다 남은 이스케이프 반쪽 (`\[`의 `\`)
    return text or None


def _clean_topics(values: list[str], existing: list[str]) -> list[str]:
    by_key = {name.casefold(): name for name in existing}
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        name = _clean_line(raw, TOPIC_NAME_MAX_CHARS + 1)
        if not 1 <= len(name) <= TOPIC_NAME_MAX_CHARS:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(by_key.get(key, name))
        if len(result) >= TOPIC_SUGGESTIONS_MAX:
            break
    return result


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise AiFailed("schema")
    return value


# ── AI로 채우기 ──────────────────────────────────────


def _topic_names(conn: sqlite3.Connection) -> list[str]:
    return [r["name"] for r in conn.execute("SELECT name FROM topics ORDER BY sort_order, id")]


def _not_fetched(title: str | None) -> dict[str, object]:
    return {
        "title": title,
        "due_date": None,
        "memo": None,
        "topic_suggestions": [],
        "content_fetched": False,
    }


@router.post("/extract")
async def extract(body: ExtractBody, request: Request) -> dict[str, object]:
    url = validate_url(body.url)
    pasted = _clean_pasted_text(body.text)

    async def work(gateway: ClaudeGateway, ticket: AiTicket, deadline: float) -> dict[str, object]:
        if pasted is not None:
            # 입력 검사는 50,000자까지 받되, AI에는 가져온 본문과 같이 앞부분만 보낸다.
            content = pasted[:FETCHED_TEXT_MAX_CHARS]
        else:
            # 서버가 외부 URL을 가져온다: 미리보기와 합산한 분당 상한 (본문을 못 얻어도 센다).
            _check_fetch_limit(request)
            if is_youtube_host(url_host(url)):
                # 유튜브는 본문을 가져오지 않는다. 제목은 미리보기 규칙(oEmbed).
                preview: PreviewFetcher = request.app.state.preview_fetcher
                return _not_fetched(await preview.fetch_title(url))
            page_fetcher: PageTextFetcher = request.app.state.page_fetcher
            page = await page_fetcher.fetch(url)
            if page.text is None:
                # 본문 없음: Claude를 부르지 않고 AI 요청 횟수에도 넣지 않는다.
                return _not_fetched(page.title)
            content = page.text[:FETCHED_TEXT_MAX_CHARS]

        database: Database = request.app.state.db
        topics: list[str] = await run_in_threadpool(_with_conn, database, _topic_names)
        message = extract_user_message(_today(request), topics, url, content)
        await _stop_if_disconnected(request)
        limiter: AiRequestLimiter = request.app.state.ai_limiter
        await _commit(limiter, ticket)
        response = await _create(
            gateway,
            limiter,
            {
                "max_tokens": EXTRACT_MAX_TOKENS,
                "system": [
                    {"type": "text", "text": EXTRACT_SYSTEM, "cache_control": {"type": "ephemeral"}}
                ],
                "messages": [{"role": "user", "content": message}],
                "output_config": {
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": EXTRACT_SCHEMA},
                },
            },
            deadline,
        )
        check_stop_reason(response, frozenset({"end_turn"}))
        data = response_json(response)
        suggestions = data.get("topic_suggestions")
        if not isinstance(suggestions, list) or not all(isinstance(s, str) for s in suggestions):
            raise AiFailed("schema")
        title = _optional_str(data, "title")
        return {
            "title": clean_title(_strip_bidi(title)) if title is not None else None,
            "due_date": _clean_due_date(_optional_str(data, "due_date")),
            # 링크 정리는 긴 글에서 수십~수백 ms 걸릴 수 있어 이벤트 루프 밖에서 한다.
            "memo": await run_in_threadpool(_clean_memo, _optional_str(data, "memo")),
            "topic_suggestions": _clean_topics(suggestions, topics),
            "content_fetched": True,
        }

    return await _run(request, EXTRACT_TIMEOUT_SECONDS, work)


# ── AI 검색 ─────────────────────────────────────────


def _tool_error(message: str) -> tuple[str, set[int], bool]:
    return json.dumps({"error": message}, ensure_ascii=False), set(), True


def _tool_url(url: str) -> str:
    """도구 결과용 URL: 쿼리·프래그먼트(·사용자 정보)를 빼고 최대 200자."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return url.split("?", 1)[0].split("#", 1)[0][:TOOL_URL_MAX_CHARS]
    return f"{parts.scheme}://{host}{port}{parts.path}"[:TOOL_URL_MAX_CHARS]


def _run_search_tool(database: Database, tool_input: object) -> tuple[str, set[int], bool]:
    """`search_scraps` 실행 → (도구 결과 JSON, 결과에 나온 id, 오류 여부)."""
    query = tool_input.get("query") if isinstance(tool_input, dict) else None
    if not isinstance(query, str):
        return _tool_error("query 문자열이 필요합니다.")
    try:
        words = parse_query(query)
    except ApiError as exc:
        return _tool_error(exc.message)
    conn = database.connect()
    try:
        items = search_list_items(conn, words, SEARCH_TOOL_LIMIT)
    except sqlite3.OperationalError:
        logger.warning("AI 검색 도구 쿼리 실패 (검색어는 기록하지 않음)")
        return _tool_error("이 검색어로는 찾을 수 없습니다. 다른 검색어로 시도하세요.")
    finally:
        conn.close()
    candidates = [
        {
            "id": item["id"],
            "title": str(item["title"])[:TOOL_TITLE_MAX_CHARS],
            "url": _tool_url(str(item["url"])),
            "source": item["source"]["name"],
            "topics": [t["name"] for t in item["topics"]][:TOOL_TOPICS_MAX],
            "due_date": item["due_date"],
            "memo_preview": item["memo_preview"],
            "liked": item["liked"],
        }
        for item in items
    ]
    ids = {int(c["id"]) for c in candidates}
    payload = {"count": len(candidates), "scraps": candidates}
    return json.dumps(payload, ensure_ascii=False), ids, False


def _picked_results(
    data: dict[str, Any], seen: set[int]
) -> tuple[str, list[tuple[int, str]], bool]:
    """(answer, [(id, reason)], AI가 결과를 하나라도 골랐는지). 형식 위반은 `AiFailed`."""
    answer = data.get("answer")
    raw = data.get("results")
    if not isinstance(answer, str) or not isinstance(raw, list):
        raise AiFailed("schema")
    picked: list[tuple[int, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise AiFailed("schema")
        scrap_id, reason = entry.get("id"), entry.get("reason")
        if type(scrap_id) is not int or not isinstance(reason, str):
            raise AiFailed("schema")
        # 이번 요청의 도구 결과에 나온 id만 (지어낸 id·중복 제거).
        if scrap_id not in seen or any(scrap_id == p for p, _ in picked):
            continue
        picked.append((scrap_id, _clean_line(reason, REASON_MAX_CHARS)))
        if len(picked) >= SEARCH_RESULTS_MAX:
            break
    return _clean_line(answer, ANSWER_MAX_CHARS), picked, bool(raw)


@router.post("/search")
async def search(body: SearchBody, request: Request) -> dict[str, object]:
    query = _clean_query(body.query)

    async def work(gateway: ClaudeGateway, ticket: AiTicket, deadline: float) -> dict[str, object]:
        database: Database = request.app.state.db
        limiter: AiRequestLimiter = request.app.state.ai_limiter
        await _commit(limiter, ticket)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": search_user_message(_today(request), query)}
        ]
        seen: set[int] = set()
        calls = 0
        data: dict[str, Any] | None = None
        for _ in range(MAX_ROUNDS):
            await _stop_if_disconnected(request)
            # 회차마다 대화가 길어지므로 매 호출 직전에 하루 토큰 예산을 확인한다.
            await _check_tokens(limiter)
            response = await _create(
                gateway,
                limiter,
                {
                    "max_tokens": SEARCH_MAX_TOKENS,
                    # 자동 캐시: 매 회차의 마지막 블록까지 캐시 → 다음 회차는 앞부분을 다시 읽는다.
                    "cache_control": {"type": "ephemeral"},
                    "system": [{"type": "text", "text": SEARCH_SYSTEM}],
                    # 도구 목록은 회차마다 똑같이 둔다
                    # (바꾸면 캐시·이전 thinking 블록이 무효가 된다).
                    # 상한을 넘으면 도구를 빼지 않고 도구 결과로 "더 쓸 수 없음"을 알린다.
                    "tools": [SEARCH_TOOL],
                    "messages": list(messages),
                    "output_config": {
                        "effort": "medium",
                        "format": {"type": "json_schema", "schema": SEARCH_SCHEMA},
                    },
                },
                deadline,
            )
            reason = check_stop_reason(response, frozenset({"end_turn", "tool_use"}))
            if reason == "end_turn":
                data = response_json(response)
                break
            uses = blocks(response, "tool_use")
            if not uses:
                raise AiFailed("tool_use without block")
            # thinking·fallback 블록까지 응답 그대로 돌려준다 (순서·내용을 바꾸지 않는다).
            messages.append({"role": "assistant", "content": response.content})
            results: list[dict[str, Any]] = []
            for use in uses:
                if getattr(use, "name", None) != SEARCH_TOOL["name"]:
                    content, ids, is_error = _tool_error("없는 도구입니다.")
                elif calls >= MAX_TOOL_CALLS:
                    content, ids, is_error = _tool_error(TOOL_LIMIT_NOTICE)
                else:
                    calls += 1
                    content, ids, is_error = await run_in_threadpool(
                        _run_search_tool, database, getattr(use, "input", None)
                    )
                seen |= ids
                result: dict[str, Any] = {
                    "type": "tool_result",
                    "tool_use_id": use.id,
                    "content": content,
                }
                if is_error:
                    result["is_error"] = True
                results.append(result)
            if calls >= MAX_TOOL_CALLS:
                results.append({"type": "text", "text": TOOL_LIMIT_NOTICE})
            messages.append({"role": "user", "content": results})
        if data is None:
            logger.warning("AI 검색이 도구 호출 회차 상한 안에 끝나지 않았습니다.")
            raise AiFailed("too many rounds")

        answer, picked, had_results = _picked_results(data, seen)
        # 응답 직전에 다시 읽는다: 그사이 지워진 스크랩은 뺀다.
        items: dict[int, dict[str, object]] = await run_in_threadpool(
            _with_conn, database, list_items_by_id, [i for i, _ in picked]
        )
        final = [{"scrap": items[i], "reason": r} for i, r in picked if i in items]
        if not final and (had_results or not answer):
            answer = NOT_FOUND_ANSWER
        elif not answer:
            answer = f"관련 스크랩 {len(final)}개를 찾았어요."
        return {"answer": answer, "results": final}

    return await _run(request, SEARCH_TIMEOUT_SECONDS, work)
