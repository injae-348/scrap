"""공통 가져오기 모듈(app/fetch.py)·본문 추출(app/pagetext.py)·파싱 동시 실행 제한(app/parsing.py).

네트워크 없이: 가짜 DNS·연결은 tests/test_preview.py 의 StubServer 를 쓴다.
"""

import asyncio
import re
import threading
import time
from pathlib import Path

import anyio
import pytest

from app.fetch import HTML_TYPES, FetchError, FetchLimits, SafeFetcher, shared_ssl_context
from app.pagetext import MIN_TEXT_CHARS, PageTextFetcher, clean_text, extract_main_text
from app.parsing import run_limited
from app.preview import PreviewFetcher
from tests.test_preview import PUBLIC_IP, StubServer, http_response

APP_DIR = Path(__file__).resolve().parent.parent / "app"


def article(paragraphs: int = 6, title: str = "공모전 안내") -> bytes:
    body = "".join(
        f"<p>{i}번째 문단: 대학생 아이디어 공모전 접수는 12월 5일까지이며"
        " 상금은 100만 원입니다.</p>"
        for i in range(paragraphs)
    )
    return (
        f"<!doctype html><html><head><title>{title}</title></head><body>"
        f"<nav>홈 메뉴</nav><article><h1>{title}</h1>{body}</article><footer>ⓒ</footer>"
        "</body></html>"
    ).encode()


def safe(server: StubServer, **limits: object) -> SafeFetcher:
    return SafeFetcher(
        limits=FetchLimits(**limits),  # type: ignore[arg-type]
        resolver=server.resolve,
        backend_factory=server.backend,
    )


def page_fetcher(server: StubServer) -> PageTextFetcher:
    return PageTextFetcher(resolver=server.resolve, backend_factory=server.backend)


# ── SafeFetcher: 스킴·포트·주소 ─────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "ftp://site.example.test/",
        "file:///etc/passwd",
        "gopher://site.example.test/",
        "javascript:alert(1)",
        "data:text/html,<title>x</title>",
        "http://site.example.test:8080/",
        "https://site.example.test:22/",
        "http://user:pw@site.example.test/",
    ],
)
def test_safe_fetcher_rejects_scheme_port_userinfo(url: str) -> None:
    server = StubServer(
        dns={"site.example.test": [PUBLIC_IP]},
        responses={PUBLIC_IP: [http_response(article())]},
    )
    with pytest.raises(FetchError):
        asyncio.run(safe(server).fetch(url, HTML_TYPES))
    assert server.dns_queries == []
    assert server.connections == []


@pytest.mark.parametrize(
    "answer",
    [["127.0.0.1"], ["10.0.0.1"], ["169.254.169.254"], ["::1"], [PUBLIC_IP, "192.168.0.2"]],
)
def test_safe_fetcher_rejects_private_addresses(answer: list[str]) -> None:
    server = StubServer(
        dns={"internal.example.test": answer},
        responses={ip: [http_response(article())] for ip in answer},
    )
    with pytest.raises(FetchError):
        asyncio.run(safe(server).fetch("http://internal.example.test/", HTML_TYPES))
    assert server.connections == []


def test_safe_fetcher_redirect_rechecked() -> None:
    server = StubServer(
        dns={"site.example.test": [PUBLIC_IP]},
        responses={
            PUBLIC_IP: [http_response(status=302, headers=[("Location", "http://10.0.0.1/")])],
            "10.0.0.1": [http_response(article())],
        },
    )
    with pytest.raises(FetchError):
        asyncio.run(safe(server).fetch("http://site.example.test/", HTML_TYPES))
    assert [c.ip for c in server.connections] == [PUBLIC_IP]


def test_safe_fetcher_success_and_media_type() -> None:
    server = StubServer(
        dns={"site.example.test": [PUBLIC_IP]},
        responses={PUBLIC_IP: [http_response(article())]},
    )
    resp = asyncio.run(safe(server).fetch("https://site.example.test/a", HTML_TYPES))
    assert resp.media_type == "text/html"
    assert resp.charset == "utf-8"
    assert "공모전" in resp.body.decode()


def test_ssl_context_shared_across_fetchers() -> None:
    a, b = SafeFetcher(), SafeFetcher()
    assert a.ssl_context is b.ssl_context is shared_ssl_context()
    assert PreviewFetcher()._ssl_context is a.ssl_context
    assert PageTextFetcher().fetcher.ssl_context is a.ssl_context


def test_user_urls_fetched_only_through_safe_fetcher() -> None:
    """앱 코드에서 사용자 URL을 가져올 수 있는 다른 HTTP 클라이언트를 쓰지 않는다."""
    forbidden = re.compile(
        r"^\s*(import|from)\s+(httpx|httpx2|urllib3|requests|aiohttp|urllib\.request)\b"
        r"|\burlopen\(|\bfetch_url\(|\bfetch_response\(",
        re.M,
    )
    offenders = [
        str(path.relative_to(APP_DIR))
        for path in APP_DIR.rglob("*.py")
        if forbidden.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
    # httpcore(연결 풀)를 직접 쓰는 곳은 공통 모듈 하나뿐이다.
    users = [
        str(path.relative_to(APP_DIR))
        for path in APP_DIR.rglob("*.py")
        if re.search(r"^\s*import httpcore\b", path.read_text(encoding="utf-8"), re.M)
    ]
    assert users == ["fetch.py"]


# ── 본문 추출 ────────────────────────────────────────


def test_extract_main_text_skips_boilerplate() -> None:
    text = extract_main_text(article().decode())
    assert text is not None
    assert "공모전 접수는 12월 5일까지" in text
    assert "홈 메뉴" not in text


def test_clean_text_controls_and_blank_lines() -> None:
    assert clean_text("a\x00b\x07\r\n\n\n\n c \t\n\td") == "ab\n\n c\n\td"


def test_page_fetcher_returns_text_and_title() -> None:
    server = StubServer(
        dns={"site.example.test": [PUBLIC_IP]},
        responses={PUBLIC_IP: [http_response(article(title="제목 &amp; 안내"))]},
    )
    page = asyncio.run(page_fetcher(server).fetch("https://site.example.test/"))
    assert page.title == "제목 & 안내"
    assert page.text is not None and len(page.text) >= MIN_TEXT_CHARS


def test_page_fetcher_short_text_is_none_but_title_kept() -> None:
    server = StubServer(
        dns={"site.example.test": [PUBLIC_IP]},
        responses={PUBLIC_IP: [http_response(article(paragraphs=1, title="짧은 글"))]},
    )
    page = asyncio.run(page_fetcher(server).fetch("https://site.example.test/"))
    assert page.text is None
    assert page.title == "짧은 글"


@pytest.mark.parametrize(
    ("url", "dns"),
    [
        ("http://internal.example.test/", {"internal.example.test": ["10.0.0.1"]}),
        ("http://site.example.test:8443/", {"site.example.test": [PUBLIC_IP]}),
        ("http://127.0.0.1/", {}),
    ],
)
def test_page_fetcher_blocked_targets(url: str, dns: dict[str, list[str]]) -> None:
    server = StubServer(
        dns=dns,
        responses={ip: [http_response(article())] for ip in (PUBLIC_IP, "10.0.0.1", "127.0.0.1")},
    )
    page = asyncio.run(page_fetcher(server).fetch(url))
    assert (page.text, page.title) == (None, None)
    assert server.connections == []


def test_page_fetcher_non_html_and_timeout() -> None:
    server = StubServer(
        dns={"site.example.test": [PUBLIC_IP]},
        responses={PUBLIC_IP: [http_response(b"{}", content_type="application/json")]},
    )
    assert asyncio.run(page_fetcher(server).fetch("https://site.example.test/")).text is None

    slow = StubServer(
        dns={"site.example.test": [PUBLIC_IP]},
        responses={PUBLIC_IP: [http_response(article())]},
        delay=5.0,
    )
    fetcher = PageTextFetcher(
        limits=FetchLimits(total_timeout=0.2), resolver=slow.resolve, backend_factory=slow.backend
    )
    started = time.monotonic()
    assert asyncio.run(fetcher.fetch("https://site.example.test/")).text is None
    assert time.monotonic() - started < 2


def test_page_fetcher_default_timeout_is_10s() -> None:
    assert PageTextFetcher().timeout == 10.0


# ── 파싱 동시 실행 제한 ───────────────────────────────


def test_run_limited_keeps_slot_until_thread_finishes() -> None:
    release = threading.Event()
    finished = threading.Event()

    def slow_parse() -> str:
        release.wait(5)
        finished.set()
        return "done"

    async def scenario() -> None:
        limiter = anyio.CapacityLimiter(1)
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await run_limited(limiter, slow_parse)
        # 기다림은 끝났지만 파싱 스레드는 아직 돌고 있으므로 자리를 반납하지 않았다.
        assert limiter.borrowed_tokens == 1
        # 다른 파싱은 자리가 날 때까지 기다린다.
        second = asyncio.ensure_future(run_limited(limiter, lambda: "second"))
        await asyncio.sleep(0.05)
        assert not second.done()
        release.set()
        assert await asyncio.wait_for(second, 2) == "second"
        assert finished.is_set()
        assert limiter.borrowed_tokens == 0

    asyncio.run(scenario())


def test_run_limited_cancelled_while_waiting_does_not_run() -> None:
    ran: list[str] = []

    async def scenario() -> None:
        limiter = anyio.CapacityLimiter(1)
        blocker = object()
        await limiter.acquire_on_behalf_of(blocker)
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await run_limited(limiter, lambda: ran.append("x"))
        limiter.release_on_behalf_of(blocker)
        await asyncio.sleep(0.05)
        assert limiter.borrowed_tokens == 0

    asyncio.run(scenario())
    assert ran == []


def test_run_limited_propagates_errors_and_releases() -> None:
    def boom() -> None:
        raise ValueError("bad html")

    async def scenario() -> None:
        limiter = anyio.CapacityLimiter(1)
        with pytest.raises(ValueError):
            await run_limited(limiter, boom)
        assert limiter.borrowed_tokens == 0

    asyncio.run(scenario())


# ── 파싱 입력 정리·사전 검사·비용 측정 ─────────────────


def test_strip_blocks() -> None:
    from app.pagetext import strip_blocks

    html = (
        "İİ<p>a</p><SCRIPT type=x>var s = '<p>';</script ><p>b</p>"
        "<scripture>keep</scripture><style>x</style><svg><g/></svg>end<noscript>tail"
    )
    assert strip_blocks(html) == "İİ<p>a</p><p>b</p><scripture>keep</scripture>end"
    many = "<p>x</p><script>s</script>" * 5000
    assert strip_blocks(many) == "<p>x</p>" * 5000


def test_prepare_html_limits() -> None:
    from app.pagetext import PARSE_INPUT_MAX_CHARS, PARSE_MAX_TAGS, prepare_html

    assert prepare_html("<p>x</p>" * (PARSE_MAX_TAGS // 2 + 1)) is None
    # 스크립트 안의 `<`는 세지 않는다
    assert prepare_html("<script>" + "<" * 100_000 + "</script><p>본문</p>") == "<p>본문</p>"
    long = prepare_html("<p>" + "가" * 900_000 + "</p>")
    assert long is not None and len(long) == PARSE_INPUT_MAX_CHARS
    assert extract_main_text("<p>x</p>" * 20_000) is None


def test_title_input_is_head_or_256kb() -> None:
    from app.preview import TITLE_INPUT_MAX_CHARS, title_input

    html = "<HTML><HEAD><title>T</title></HEAD><body>" + "x" * 10 + "</body>"
    assert title_input(html) == "<HTML><HEAD><title>T</title></HEAD>"
    assert len(title_input("<title>t</title>" + "y" * 1_000_000)) == TITLE_INPUT_MAX_CHARS


_MEASURE = r"""
import json, resource, sys, time
from app.pagetext import extract_main_text, _trafilatura
_trafilatura()
units = {
    "p": "<p>x</p>",
    "div": "<div><div><div><span>가나</span></div></div></div>",
    "a": '<a href="https://ex.test/aaaa" class="c1 c2" data-x="1" title="t">링크</a>',
    "script": "<p>본문 문단입니다.</p><script>var x = '<div><div>';</script>",
}
html = "<html><body><article>" + units[sys.argv[1]] * (1_000_000 // len(units[sys.argv[1]]))
html += "</article></body></html>"
def rss_mb():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / 1048576 if sys.platform == "darwin" else r / 1024
before = rss_mb(); start = time.perf_counter()
extract_main_text(html)
print(json.dumps({"sec": time.perf_counter() - start, "rss_mb": rss_mb() - before}))
"""


@pytest.mark.parametrize("kind", ["p", "div", "a", "script"])
def test_parse_cost_bounded(kind: str) -> None:
    """1MB 합성 페이지의 본문 추출이 시간·메모리 상한 안에서 끝난다.

    libxml2 메모리는 tracemalloc 에 잡히지 않으므로 별도 프로세스에서 RSS 로 잰다.
    """
    import json
    import subprocess
    import sys

    out = subprocess.run(  # noqa: S603 — 테스트 전용 고정 스크립트
        [sys.executable, "-c", _MEASURE, kind],
        cwd=APP_DIR.parent,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["sec"] < 3.0, result
    assert result["rss_mb"] < 120, result
