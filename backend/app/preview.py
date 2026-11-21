"""제목 미리보기 (docs/API.md v1.3 "제목 미리보기").

가져오기는 공통 모듈 `app.fetch.SafeFetcher`만 쓴다 (포트 80·443, 공인 IP만, 리다이렉트 5번 재검사,
1MB, 동시 2개 — 규칙은 app/fetch.py). 이 모듈은 그 위에서
- 유튜브(`youtube.com`·`youtu.be`)는 oEmbed(JSON), 그 외는 HTML에서 `og:title` → `twitter:title` →
  `<title>` 순으로 제목을 찾는다. 전체 5초.
- HTML 파싱은 표준 라이브러리 `html.parser`만 쓰고, 전용 동시 실행 제한(1개)으로 스레드에서
  돌린다 (`app.parsing.run_limited`: 시간 초과로 기다림이 끝나도 파싱이 끝날 때까지 자리를 반납하지
  않는다).
- 실패는 예외가 아니라 None (API는 200 + `title: null`). 로그에는 URL을 남기지 않는다.
"""

import asyncio
import json
import logging
import ssl
import string
import unicodedata
from html.parser import HTMLParser
from urllib.parse import quote

import anyio

from app.fetch import (
    FETCH_FAILURES,
    HTML_TYPES,
    JSON_TYPES,
    USER_AGENT,
    BackendFactory,
    BodyDecoder,
    FetchError,
    FetchLimits,
    FetchSlots,
    PinnedBackend,
    Resolver,
    SafeFetcher,
    decode_html,
    parse_target,
)
from app.parsing import run_limited

logger = logging.getLogger("app")

# 다른 모듈·테스트가 쓰던 이름 (가져오기 구현은 app/fetch.py 로 옮겼다).
__all__ = [
    "USER_AGENT",
    "FetchLimits",
    "PinnedBackend",
    "PreviewFetcher",
    "clean_title",
    "decode_html",
    "extract_title",
    "is_youtube_host",
    "title_input",
]
_Decoder = BodyDecoder

TITLE_MAX_LENGTH = 300
# 길이가 바뀌지 않는 소문자화 (ASCII만).
# `str.lower()`는 일부 문자에서 길이가 바뀌어 위치가 어긋난다.
_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


def ascii_lower(value: str) -> str:
    return value.translate(_ASCII_LOWER)


# 제목 파싱 입력: `</head>`까지 또는 앞 256KB 중 짧은 쪽 (제목 후보는 머리말에 있다).
TITLE_INPUT_MAX_CHARS = 256 * 1024
YOUTUBE_HOSTS = ("youtube.com", "youtu.be")
YOUTUBE_OEMBED = "https://www.youtube.com/oembed?format=json&url="


# ── 제목 해석 ────────────────────────────────────────


def clean_title(value: str | None) -> str | None:
    """공백을 하나로 모으고 제어문자를 빼서 최대 300자. 비면 None."""
    if not value:
        return None
    text = " ".join(value.split())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cc")
    text = text.strip()[:TITLE_MAX_LENGTH].strip()
    return text or None


class _Done(Exception):
    pass


class _TitleParser(HTMLParser):
    """og:title → twitter:title → <title>. 속성값·본문의 HTML 엔티티는 파서가 풀어 준다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.og: str | None = None
        self.twitter: str | None = None
        self.title: str | None = None
        self._title_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "meta":
            values = {k.lower(): (v or "") for k, v in attrs}
            keys = {
                values.get("property", "").strip().lower(),
                values.get("name", "").strip().lower(),
            }
            content = clean_title(values.get("content"))
            if content is None:
                return
            if "og:title" in keys and self.og is None:
                self.og = content
                raise _Done  # 가장 우선인 값을 찾았으면 더 읽지 않는다
            if "twitter:title" in keys and self.twitter is None:
                self.twitter = content
        elif tag == "title" and self.title is None and self._title_parts is None:
            self._title_parts = []
        elif tag == "body" and (self.twitter or self.title):
            raise _Done  # 머리말(head)이 끝났고 후보가 있으면 멈춘다

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._title_parts is not None:
            self.title = clean_title("".join(self._title_parts)) or ""
            self._title_parts = None

    def handle_data(self, data: str) -> None:
        if self._title_parts is not None:
            self._title_parts.append(data)


def title_input(html: str) -> str:
    """제목 파싱에 넘길 부분: `</head>`까지(포함) 또는 앞 `TITLE_INPUT_MAX_CHARS`자 중 짧은 쪽."""
    head = html[:TITLE_INPUT_MAX_CHARS]
    end = ascii_lower(head).find("</head")
    return head if end == -1 else head[: end + len("</head>")]


def extract_title(html: str) -> str | None:
    parser = _TitleParser()
    try:
        parser.feed(html)
        parser.close()
    except _Done:
        pass
    except Exception:  # noqa: BLE001 — 깨진 HTML: 지금까지 찾은 값으로 판단
        logger.debug("HTML 파싱 중단", exc_info=True)
    if parser.title is None and parser._title_parts is not None:
        parser.title = clean_title("".join(parser._title_parts))
    return parser.og or parser.twitter or parser.title or None


def is_youtube_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in YOUTUBE_HOSTS)


# ── 가져오기 ────────────────────────────────────────


class PreviewFetcher:
    """`/meta/preview`의 제목 가져오기. 앱마다 하나(`app.state.preview_fetcher`).

    테스트는 `resolver`(DNS)와 `backend_factory`(TCP 연결)를 바꿔 네트워크 없이 검사한다.
    """

    def __init__(
        self,
        limits: FetchLimits | None = None,
        resolver: Resolver | None = None,
        backend_factory: BackendFactory | None = None,
    ) -> None:
        self.fetcher = SafeFetcher(limits, resolver, backend_factory)
        self.limits = self.fetcher.limits
        # 제목 파싱 전용 동시 실행 제한 (본문 추출과 따로).
        self._parse_limiter = anyio.CapacityLimiter(1)

    @property
    def _slots(self) -> FetchSlots:
        return self.fetcher.slots

    @property
    def _ssl_context(self) -> ssl.SSLContext:
        return self.fetcher.ssl_context

    async def fetch_title(self, url: str) -> str | None:
        try:
            async with asyncio.timeout(self.limits.total_timeout):
                if is_youtube_host(parse_target(url).host):
                    return await self._youtube_title(url)
                return await self._html_title(url)
        except FETCH_FAILURES as exc:
            # URL 은 로그에 남기지 않는다 (사용자가 저장하려는 주소).
            logger.info("제목 미리보기 실패: %s", type(exc).__name__)
        except Exception as exc:  # noqa: BLE001 — 미리보기는 실패해도 200 + null
            logger.warning("제목 미리보기 예외: %s", type(exc).__name__)
        return None

    async def _html_title(self, url: str) -> str | None:
        resp = await self.fetcher.fetch(url, HTML_TYPES)
        html = decode_html(resp.body, resp.charset)
        return await run_limited(self._parse_limiter, extract_title, title_input(html))

    async def _youtube_title(self, url: str) -> str | None:
        oembed = YOUTUBE_OEMBED + quote(parse_target(url).url, safe="")
        resp = await self.fetcher.fetch(oembed, JSON_TYPES)
        try:
            data = json.loads(resp.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise FetchError("bad json") from exc
        title = data.get("title") if isinstance(data, dict) else None
        return clean_title(title) if isinstance(title, str) else None
