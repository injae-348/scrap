"""AI로 채우기용 페이지 본문 추출 (docs/API.md v1.5 "AI로 채우기").

- 가져오기는 공통 모듈 `app.fetch.SafeFetcher`만 쓴다 (규칙은 제목 미리보기와 같다: http/https,
  포트 80·443, 공인 IP만, 리다이렉트 5번 재검사, 1MB, HTML만). 이 기능 전체(가져오기 + 파싱) 10초.
- HTML → 본문 텍스트는 trafilatura(lxml 기반, 브라우저 없음)에 **문자열로만** 넘긴다.
  trafilatura의 내장 가져오기(`fetch_url` 등)는 쓰지 않는다.
- 파싱 전 정리·사전 검사 (`prepare_html`): 본문과 상관없는 블록(`<script>`·`<style>`·`<svg>`
  등)을 선형 탐색으로 덜어 내고, 남은 태그 수(`<` 개수)가 `PARSE_MAX_TAGS`를 넘으면 파싱하지 않고
  "본문 없음"으로 처리한다. trafilatura에는 그 결과의 앞부분 `PARSE_INPUT_MAX_CHARS`자만 넘긴다.
  (파싱 시간·메모리는 문서 요소 수에 따라 빠르게 늘어난다. 측정: tests/test_fetch.py
  `test_parse_cost_bounded`.)
- 제목은 `<head>`(또는 앞 256KB)만 파싱한다 (`app.preview.title_input`).
- 파싱은 전용 동시 실행 제한(1개)으로 스레드에서 돌린다 (`app.parsing.run_limited`: 시간 초과로
  기다림이 끝나도 파싱이 끝날 때까지 자리를 반납하지 않는다).
- 실패는 예외가 아니라 `PageContent(text=None, ...)`. 로그에는 URL·본문을 남기지 않는다.

trafilatura는 처음 쓸 때 불러온다 (AI 기능을 쓰지 않으면 메모리를 차지하지 않게).
"""

import asyncio
import functools
import logging
import re
import unicodedata
import warnings
from dataclasses import dataclass
from types import ModuleType
from typing import Any

import anyio

from app.fetch import (
    FETCH_FAILURES,
    HTML_TYPES,
    BackendFactory,
    FetchLimits,
    Resolver,
    SafeFetcher,
    decode_html,
)
from app.parsing import run_limited
from app.preview import ascii_lower, extract_title, title_input

logger = logging.getLogger("app")

FETCH_TIMEOUT_SECONDS = 10.0
# trafilatura 입력 상한 (블록 정리 뒤 앞부분). AI에는 어차피 앞 20,000자만 보낸다.
PARSE_INPUT_MAX_CHARS = 512 * 1024
# 블록 정리 뒤 `<` 개수가 이보다 많으면 파싱하지 않는다 (보통 기사 페이지는 이보다 훨씬 적다).
PARSE_MAX_TAGS = 30_000
# trafilatura 설정: 추출 **결과** 트리의 직계 요소가 이보다 많으면 결과를 버린다 (사후 검사).
PARSE_MAX_TREE_SIZE = 50_000
# 본문과 상관없어 파싱 전에 덜어 내는 블록.
SKIPPED_BLOCKS = ("script", "style", "svg", "noscript", "template")
# 이보다 짧으면 "본문을 얻지 못함"으로 본다.
MIN_TEXT_CHARS = 200

_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class PageContent:
    text: str | None  # 본문 (MIN_TEXT_CHARS 미만이면 None)
    title: str | None  # og:title → twitter:title → <title> (제목 미리보기와 같은 규칙)


@functools.cache
def _trafilatura() -> tuple[ModuleType, Any]:
    with warnings.catch_warnings():
        # 쓰지 않는 내장 가져오기 모듈(urllib3 SOCKS)의 선택 의존성 경고를 숨긴다.
        warnings.simplefilter("ignore")
        import trafilatura
        from trafilatura.settings import use_config
    config = use_config()
    config.set("DEFAULT", "MAX_TREE_SIZE", str(PARSE_MAX_TREE_SIZE))
    config.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")
    return trafilatura, config


def clean_text(value: str) -> str:
    """제어문자(줄바꿈·탭 제외) 제거, 줄 끝 공백 정리, 빈 줄 3개 이상은 2개로."""
    text = "".join(
        ch for ch in value.replace("\r\n", "\n") if ch in "\n\t" or unicodedata.category(ch) != "Cc"
    )
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return _BLANK_LINES.sub("\n\n", text).strip()


def strip_blocks(html: str) -> str:
    """`SKIPPED_BLOCKS` 요소를 여는 태그부터 닫는 태그까지 지운다 (대소문자 무시, 선형 시간).

    닫는 태그가 없으면 그 뒤를 모두 버린다.
    """
    lower = ascii_lower(html)
    n = len(html)
    parts: list[str] = []
    pos = 0
    # 이름마다 "다음 여는 태그 위치"를 기억해 두고, 지나간 것만 다시 찾는다
    # (같은 구간을 반복해 읽지 않게).
    nxt: dict[str, int] = {}

    def find_open(name: str, start: int) -> int:
        i = lower.find("<" + name, start)
        while i != -1:
            after = i + 1 + len(name)
            if after >= n or lower[after] in " \t\r\n/>":
                return i
            i = lower.find("<" + name, after)
        return n

    for name in SKIPPED_BLOCKS:
        nxt[name] = find_open(name, 0)
    while True:
        name = min(nxt, key=lambda k: nxt[k])
        start = nxt[name]
        if start >= n:
            break
        parts.append(html[pos:start])
        close = lower.find("</" + name, start)
        if close == -1:
            pos = n
            break
        end = lower.find(">", close)
        pos = n if end == -1 else end + 1
        for key, value in nxt.items():
            if value < pos:
                nxt[key] = find_open(key, pos)
    parts.append(html[pos:])
    return "".join(parts)


def prepare_html(html: str) -> str | None:
    """trafilatura에 넘길 입력. 태그가 너무 많으면 None (파싱하지 않음)."""
    cleaned = strip_blocks(html)
    if cleaned.count("<") > PARSE_MAX_TAGS:
        return None
    return cleaned[:PARSE_INPUT_MAX_CHARS]


def extract_main_text(html: str) -> str | None:
    """HTML 문자열 → 본문 텍스트 (네트워크 없음). 못 찾거나 사전 검사에 걸리면 None."""
    prepared = prepare_html(html)
    if prepared is None:
        logger.info("본문 추출 건너뜀: 문서 요소가 너무 많음")
        return None
    trafilatura, config = _trafilatura()
    try:
        text = trafilatura.extract(
            prepared,
            output_format="txt",
            include_comments=False,
            include_tables=True,
            include_images=False,
            include_links=False,
            with_metadata=False,
            favor_recall=True,
            config=config,
        )
    except Exception as exc:  # noqa: BLE001 — 깨진 HTML: 본문 없음으로 처리
        logger.info("본문 추출 실패: %s", type(exc).__name__)
        return None
    if not text:
        return None
    return clean_text(text) or None


class PageTextFetcher:
    """`/ai/extract`의 본문 가져오기. 앱마다 하나(`app.state.page_fetcher`)."""

    def __init__(
        self,
        limits: FetchLimits | None = None,
        resolver: Resolver | None = None,
        backend_factory: BackendFactory | None = None,
    ) -> None:
        self.fetcher = SafeFetcher(
            limits or FetchLimits(total_timeout=FETCH_TIMEOUT_SECONDS), resolver, backend_factory
        )
        self.timeout = self.fetcher.limits.total_timeout
        # 본문 파싱 전용 동시 실행 제한.
        self.parse_limiter = anyio.CapacityLimiter(1)

    async def fetch(self, url: str) -> PageContent:
        title: str | None = None
        text: str | None = None
        try:
            async with asyncio.timeout(self.timeout):
                resp = await self.fetcher.fetch(url, HTML_TYPES)
                html = decode_html(resp.body, resp.charset)
                del resp
                title = await run_limited(self.parse_limiter, extract_title, title_input(html))
                text = await run_limited(self.parse_limiter, extract_main_text, html)
        except FETCH_FAILURES as exc:
            logger.info("본문 가져오기 실패: %s", type(exc).__name__)
        except Exception as exc:  # noqa: BLE001 — 실패하면 "본문 없음" (붙여넣기 안내)
            logger.warning("본문 가져오기 예외: %s", type(exc).__name__)
        if text is not None and len(text) < MIN_TEXT_CHARS:
            text = None
        return PageContent(text=text, title=title)
