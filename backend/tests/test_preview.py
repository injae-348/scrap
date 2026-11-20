"""제목 미리보기 `POST /meta/preview`와 안전한 가져오기 (네트워크 없이).

DNS(`resolver`)와 TCP 연결(`PinnedBackend`의 안쪽 백엔드)을 가짜로 바꾼다. 실제 `PinnedBackend`를
그대로 써서 "검사한 IP로만 연결한다"는 동작까지 확인한다.
"""

import asyncio
import gzip
import ipaddress
import json
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpcore
import pytest
from fastapi.testclient import TestClient

from app.netguard import is_public_ip
from app.preview import (
    USER_AGENT,
    FetchLimits,
    PinnedBackend,
    PreviewFetcher,
    clean_title,
    decode_html,
    extract_title,
)

PUBLIC_IP = "93.184.215.14"  # 공인 대역의 임의 주소 (실제로 연결하지 않음)
PUBLIC_IP_2 = "93.184.215.15"
YOUTUBE_IP = "142.250.0.1"


# ── 가짜 네트워크 ────────────────────────────────────


def http_response(
    body: bytes = b"",
    status: int = 200,
    content_type: str | None = "text/html; charset=utf-8",
    headers: Iterable[tuple[str, str]] = (),
    content_length: bool = True,
) -> bytes:
    lines = [f"HTTP/1.1 {status} X"]
    if content_type:
        lines.append(f"Content-Type: {content_type}")
    lines.extend(f"{k}: {v}" for k, v in headers)
    if content_length:
        lines.append(f"Content-Length: {len(body)}")
    lines.append("Connection: close")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body


def html(head: str = "", body: str = "") -> bytes:
    return f"<!doctype html><html><head>{head}</head><body>{body}</body></html>".encode()


@dataclass
class Connection:
    host_arg: str
    ip: str
    port: int
    sni: str | None = None
    request: bytes = b""
    read_bytes: int = 0


class StubStream(httpcore.AsyncNetworkStream):
    def __init__(self, server: "StubServer", conn: Connection, data: bytes, delay: float) -> None:
        self._server = server
        self._conn = conn
        self._data = data
        self._delay = delay

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        if self._delay:
            await asyncio.sleep(self._delay)
        chunk, self._data = self._data[:max_bytes], self._data[max_bytes:]
        self._conn.read_bytes += len(chunk)
        return chunk

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._conn.request += buffer

    async def aclose(self) -> None:
        self._server.open -= 1

    async def start_tls(
        self, ssl_context: Any, server_hostname: str | None = None, timeout: float | None = None
    ) -> "StubStream":
        self._conn.sni = server_hostname
        return self

    def get_extra_info(self, info: str) -> Any:
        return None


@dataclass
class StubServer:
    """IP별로 응답 목록을 차례로 돌려주는 가짜 서버들 + 가짜 DNS."""

    dns: dict[str, list[str]] = field(default_factory=dict)
    responses: dict[str, list[bytes]] = field(default_factory=dict)
    delay: float = 0.0
    connections: list[Connection] = field(default_factory=list)
    dns_queries: list[str] = field(default_factory=list)
    attempts: list[str] = field(default_factory=list)  # 연결을 시도한 모든 IP (응답이 없어도)
    open: int = 0
    max_open: int = 0

    async def resolve(self, host: str, port: int) -> list[str]:
        self.dns_queries.append(host)
        answer = self.dns.get(host)
        if answer is None:
            raise OSError("NXDOMAIN")
        # 함수로 넣으면 질의할 때마다 다른 답 (DNS rebinding 흉내)
        return answer() if callable(answer) else list(answer)

    def backend(self, host: str, ips: list[str]) -> PinnedBackend:
        return PinnedBackend(host, ips, inner=_Inner(self))


class _Inner(httpcore.AsyncNetworkBackend):
    def __init__(self, server: StubServer) -> None:
        self.server = server

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        self.server.attempts.append(host)
        queue = self.server.responses.get(host)
        if not queue:
            raise httpcore.ConnectError("refused")
        conn = Connection(host_arg=host, ip=host, port=port)
        self.server.connections.append(conn)
        self.server.open += 1
        self.server.max_open = max(self.server.max_open, self.server.open)
        return StubStream(self.server, conn, queue.pop(0), self.server.delay)

    async def connect_unix_socket(self, *args: Any, **kwargs: Any) -> httpcore.AsyncNetworkStream:
        raise AssertionError

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def make_fetcher(server: StubServer, **limits: Any) -> PreviewFetcher:
    return PreviewFetcher(
        limits=FetchLimits(**limits), resolver=server.resolve, backend_factory=server.backend
    )


def fetch(server: StubServer, url: str, **limits: Any) -> str | None:
    return asyncio.run(make_fetcher(server, **limits).fetch_title(url))


def site(body: bytes, host: str = "site.example.test", ip: str = PUBLIC_IP) -> StubServer:
    return StubServer(dns={host: [ip]}, responses={ip: [body]})


# ── IP 검사 ─────────────────────────────────────────


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "127.255.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.0.1",
        "169.254.169.254",  # 클라우드 메타데이터
        "100.64.0.1",  # CGNAT
        "100.127.255.254",
        "0.0.0.0",  # noqa: S104
        "0.1.2.3",
        "224.0.0.1",
        "239.255.255.250",
        "255.255.255.255",
        "240.0.0.1",
        "192.0.2.1",  # 문서용
        "198.18.0.1",  # 벤치마크
        "192.0.0.8",
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "fd12:3456::1",
        "fec0::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "::ffff:169.254.169.254",
        "64:ff9b::7f00:1",  # NAT64 안의 127.0.0.1
        "64:ff9b::a00:1",  # NAT64 안의 10.0.0.1
        "64:ff9b:1::1",
        "2002:7f00:1::1",  # 6to4 안의 127.0.0.1
        "2002:c0a8:1::1",  # 6to4 안의 192.168.0.1
        "2001:0:4136:e378:8000:63bf:3fff:fdd2",  # Teredo
        "2001:db8::1",  # 문서용
        "::127.0.0.1",  # IPv4-compatible
        "100::1",
    ],
)
def test_non_public_addresses_rejected(address: str) -> None:
    assert is_public_ip(ipaddress.ip_address(address)) is False


@pytest.mark.parametrize(
    "address",
    ["8.8.8.8", "1.1.1.1", PUBLIC_IP, "2606:4700:4700::1111", "::ffff:8.8.8.8", "64:ff9b::808:808"],
)
def test_public_addresses_allowed(address: str) -> None:
    assert is_public_ip(ipaddress.ip_address(address)) is True


# ── 가져오기 ────────────────────────────────────────


def test_fetch_og_title_and_request_shape() -> None:
    server = site(http_response(html('<meta property="og:title" content="  OG &amp; 제목 ">')))
    assert fetch(server, "https://site.example.test/a%20b/경로?q=한글&x=%2F#frag") == "OG & 제목"
    (conn,) = server.connections
    assert conn.ip == PUBLIC_IP
    assert conn.port == 443
    assert conn.sni == "site.example.test"  # SNI·인증서 검증은 원래 호스트 이름
    request = conn.request.decode("latin-1")
    assert request.startswith(
        "GET /a%20b/%EA%B2%BD%EB%A1%9C?q=%ED%95%9C%EA%B8%80&x=%2F HTTP/1.1\r\n"
    )  # 기존 퍼센트 인코딩 유지, 비ASCII만 인코딩, fragment 제외
    assert "Host: site.example.test\r\n" in request
    assert f"User-Agent: {USER_AGENT}\r\n" in request
    assert "Cookie" not in request and "Authorization" not in request


def test_http_and_explicit_standard_ports() -> None:
    server = site(http_response(html("<title>T</title>")))
    assert fetch(server, "http://site.example.test:80") == "T"
    (conn,) = server.connections
    assert conn.port == 80
    assert conn.sni is None
    assert "Host: site.example.test\r\n" in conn.request.decode()

    server = site(http_response(html("<title>S</title>")))
    assert fetch(server, "https://site.example.test:443/") == "S"
    assert server.connections[0].port == 443


@pytest.mark.parametrize(
    "url",
    [
        "http://site.example.test:8080/",
        "https://site.example.test:8443/",
        "http://site.example.test:25/",
        "http://site.example.test:6379/",
    ],
)
def test_non_standard_port_not_fetched(url: str) -> None:
    server = site(http_response(html("<title>T</title>")))
    assert fetch(server, url) is None
    assert server.connections == []
    assert server.dns_queries == []


def test_redirect_to_non_standard_port_blocked() -> None:
    server = site(b"")
    server.responses[PUBLIC_IP] = [
        http_response(status=302, headers=[("Location", "http://site.example.test:2525/")]),
        http_response(html("<title>other port</title>")),
    ]
    assert fetch(server, "https://site.example.test/") is None
    assert len(server.connections) == 1


def test_fetched_title_control_chars_removed() -> None:
    server = site(http_response(html("<title>제\x00목\x07 &#7; 끝</title>")))
    assert fetch(server, "https://site.example.test/") == "제목 끝"


@pytest.mark.parametrize(
    "url",
    [
        "http://2130706433/",  # 10진
        "http://0x7f000001/",  # 16진
        "http://0x7f.1/",
        "http://0177.0.0.1/",  # 8진
        "http://127.1/",  # 짧은 표기
        "http://0/",
        "http://[::ffff:7f00:1]/",
        "http://localhost/",
        "http://localhost./",
    ],
)
def test_alternative_ipv4_notation_never_connects(url: str) -> None:
    """실제 시스템 resolver로 푼다 (숫자 표기 해석은 로컬에서 끝나 네트워크가 필요 없다)."""
    loopback = ("127.0.0.1", "::1", "0.0.0.0")  # noqa: S104
    server = StubServer(
        responses={ip: [http_response(html("<title>x</title>"))] for ip in loopback}
    )
    fetcher = PreviewFetcher(backend_factory=server.backend)  # resolver 는 기본값(system_resolve)
    assert asyncio.run(fetcher.fetch_title(url)) is None
    assert server.connections == []
    # 표기 해석은 플랫폼마다 다를 수 있다 (예: 0177.0.0.1 을 8진 또는 10진으로). 어느 쪽이든
    # 연결은 검사를 통과한 공인 주소로만 시도한다.
    assert all(is_public_ip(ipaddress.ip_address(ip)) for ip in server.attempts), server.attempts


def test_ssl_context_created_once() -> None:
    fetcher = make_fetcher(StubServer())
    first = fetcher._ssl_context
    asyncio.run(fetcher.fetch_title("https://nowhere.example.test/"))
    assert fetcher._ssl_context is first


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        ('<meta name="twitter:title" content="TW"><title>T</title>', "TW"),
        ('<title>T</title><meta property="twitter:title" content="TW">', "TW"),
        (
            '<title>T</title><meta name="twitter:title" content="TW">'
            '<meta property="og:title" content="OG">',
            "OG",
        ),
        ('<meta property="og:title" content="   "><title>  긴\n\n  제목 </title>', "긴 제목"),
        ("<title>&lt;b&gt; &#xD55C;&#44544; &quot;q&quot;</title>", '<b> 한글 "q"'),
        ("<TITLE>Upper</TITLE>", "Upper"),
        ("", None),
        ("<title></title>", None),
        ('<meta property="og:title">', None),
    ],
)
def test_title_priority(head: str, expected: str | None) -> None:
    assert extract_title(html(head).decode()) == expected


def test_title_length_and_control_chars() -> None:
    assert clean_title("a\x00b\x07c") == "abc"
    assert len(clean_title("가" * 1000) or "") == 300
    assert extract_title("<title>unterminated title") == "unterminated title"
    assert extract_title("<<<>>><title>깨진 HTML 이후</title><meta") == "깨진 HTML 이후"


def test_charset_handling() -> None:
    euc = "<html><head><meta charset='euc-kr'><title>한글 제목</title></head></html>".encode(
        "cp949"
    )
    assert decode_html(euc, None).count("한글 제목") == 1
    header = "<title>헤더 문자셋</title>".encode("cp949")
    assert "헤더 문자셋" in decode_html(header, "EUC-KR")
    http_equiv = (
        b'<meta http-equiv="Content-Type" content="text/html; charset=windows-1252">'
        b"<title>caf\xe9</title>"
    )
    assert "café" in decode_html(http_equiv, None)
    assert "제목" in decode_html("﻿<title>제목</title>".encode(), "iso-8859-1")  # BOM 우선
    assert "x" in decode_html(b"<title>x</title>", "no-such-charset")
    assert "x" in decode_html(b"<title>x</title>", "base64")  # 문자 인코딩이 아닌 코덱 무시

    server = site(
        http_response(
            "<title>서버 문자셋</title>".encode("cp949"), content_type="text/html; charset=euc-kr"
        )
    )
    assert fetch(server, "https://site.example.test/") == "서버 문자셋"


def test_gzip_body() -> None:
    body = gzip.compress(html("<title>압축</title>"))
    server = site(http_response(body, headers=[("Content-Encoding", "gzip")]))
    assert fetch(server, "https://site.example.test/") == "압축"


def test_unknown_encoding_fails() -> None:
    server = site(http_response(b"xx", headers=[("Content-Encoding", "br")]))
    assert fetch(server, "https://site.example.test/") is None


@pytest.mark.parametrize(
    "content_type",
    ["image/png", "application/json", "text/plain", "application/octet-stream", None],
)
def test_non_html_rejected(content_type: str | None) -> None:
    server = site(http_response(html("<title>T</title>"), content_type=content_type))
    assert fetch(server, "https://site.example.test/") is None


@pytest.mark.parametrize("status", [404, 500, 204, 304])
def test_non_200_fails(status: int) -> None:
    server = site(http_response(html("<title>T</title>"), status=status))
    assert fetch(server, "https://site.example.test/") is None


# ── SSRF 방어 ───────────────────────────────────────


@pytest.mark.parametrize(
    "answer",
    [
        ["127.0.0.1"],
        ["10.0.0.5"],
        ["169.254.169.254"],
        ["::1"],
        ["100.64.1.1"],
        [PUBLIC_IP, "10.0.0.5"],
    ],
)
def test_host_resolving_to_private_ip_blocked(answer: list[str]) -> None:
    server = StubServer(
        dns={"internal.example.test": answer},
        responses={ip: [http_response(html("<title>secret</title>"))] for ip in answer},
    )
    assert fetch(server, "http://internal.example.test/") is None
    assert server.connections == []  # 연결 시도 자체가 없다


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.0.0.1:8000/api/health",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/",
        "http://10.0.0.1/",
    ],
)
def test_ip_literal_private_blocked(url: str) -> None:
    server = StubServer(responses={})
    assert fetch(server, url) is None
    assert server.connections == []
    assert server.dns_queries == []


def test_ip_literal_public_allowed() -> None:
    server = StubServer(responses={PUBLIC_IP: [http_response(html("<title>IP</title>"))]})
    assert fetch(server, f"http://{PUBLIC_IP}/") == "IP"


def test_dns_rebinding_uses_checked_ip() -> None:
    answers = iter([[PUBLIC_IP], ["127.0.0.1"], ["127.0.0.1"]])
    server = StubServer(
        dns={"rebind.example.test": lambda: next(answers)},
        responses={
            PUBLIC_IP: [http_response(html("<title>public</title>"))],
            "127.0.0.1": [http_response(html("<title>internal</title>"))],
        },
    )
    assert fetch(server, "http://rebind.example.test/") == "public"
    assert [c.ip for c in server.connections] == [PUBLIC_IP]
    assert server.dns_queries == ["rebind.example.test"]  # 한 번만 풀고 그 IP로 연결


def test_pinned_backend_ignores_other_hosts() -> None:
    backend = StubServer(responses={PUBLIC_IP: [b""]}).backend("a.example.test", [PUBLIC_IP])
    with pytest.raises(httpcore.ConnectError):
        asyncio.run(backend.connect_tcp("b.example.test", 80))


def test_multiple_ips_tried_in_order() -> None:
    server = StubServer(
        dns={"multi.example.test": ["2606:4700:4700::1111", PUBLIC_IP_2, PUBLIC_IP]},
        responses={PUBLIC_IP: [http_response(html("<title>second</title>"))]},
    )
    assert fetch(server, "http://multi.example.test/") == "second"


@pytest.mark.parametrize(
    "location",
    [
        "http://internal.example.test/",  # 사설 IP로 풀리는 호스트
        "http://127.0.0.1/",
        "http://[::1]:8000/",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
        "gopher://site.example.test/",
        "ftp://site.example.test/",
        "javascript:alert(1)",
        "//127.0.0.1/",  # 스킴 생략 → 현재 스킴으로 127.0.0.1
    ],
)
def test_redirect_to_disallowed_target_blocked(location: str) -> None:
    server = StubServer(
        dns={"site.example.test": [PUBLIC_IP], "internal.example.test": ["192.168.1.10"]},
        responses={
            PUBLIC_IP: [http_response(status=302, headers=[("Location", location)])],
            "192.168.1.10": [http_response(html("<title>secret</title>"))],
            "127.0.0.1": [http_response(html("<title>secret</title>"))],
            "::1": [http_response(html("<title>secret</title>"))],
            "169.254.169.254": [http_response(html("<title>secret</title>"))],
        },
    )
    assert fetch(server, "http://site.example.test/") is None
    assert [c.ip for c in server.connections] == [PUBLIC_IP]


def test_redirects_followed_up_to_five() -> None:
    hops = [
        http_response(status=301 + (i % 2), headers=[("Location", f"/step{i + 1}")])
        for i in range(5)
    ]
    server = site(b"")
    server.responses[PUBLIC_IP] = [*hops, http_response(html("<title>도착</title>"))]
    assert fetch(server, "https://site.example.test/step0") == "도착"
    assert len(server.connections) == 6
    assert server.connections[-1].request.startswith(b"GET /step5 ")
    assert len(server.dns_queries) == 6  # 매 단계 다시 검사


def test_sixth_redirect_fails() -> None:
    server = site(b"")
    server.responses[PUBLIC_IP] = [
        http_response(status=307, headers=[("Location", f"/r{i}")]) for i in range(7)
    ]
    assert fetch(server, "https://site.example.test/") is None
    assert len(server.connections) == 6


def test_redirect_to_other_public_host() -> None:
    server = StubServer(
        dns={"a.example.test": [PUBLIC_IP], "b.example.test": [PUBLIC_IP_2]},
        responses={
            PUBLIC_IP: [
                http_response(status=308, headers=[("Location", "https://b.example.test/x")])
            ],
            PUBLIC_IP_2: [http_response(html("<title>B</title>"))],
        },
    )
    assert fetch(server, "http://a.example.test/") == "B"
    assert server.connections[1].sni == "b.example.test"


def test_redirect_without_location_fails() -> None:
    assert fetch(site(http_response(status=302)), "https://site.example.test/") is None


def test_body_read_limited_to_1mb() -> None:
    late_title = b"<html><head>" + b"<!--" + b"x" * (1024 * 1024 + 10) + b"-->"
    late_title += b'<meta property="og:title" content="too late"></head></html>'
    late_title += b"y" * (3 * 1024 * 1024)
    server = site(http_response(late_title))
    assert fetch(server, "https://site.example.test/") is None
    (conn,) = server.connections
    assert conn.read_bytes < 1024 * 1024 + 256 * 1024  # 4MB 넘는 응답 중 앞부분만 읽었다


def test_body_without_content_length_limited() -> None:
    body = html("<title>앞부분</title>") + b"z" * (5 * 1024 * 1024)
    server = site(http_response(body, content_length=False))
    assert fetch(server, "https://site.example.test/") == "앞부분"
    assert server.connections[0].read_bytes < 1024 * 1024 + 256 * 1024


def test_decoder_never_unbounded() -> None:
    from app.preview import _Decoder

    decoder = _Decoder("gzip", 10)
    data, full = decoder.feed(gzip.compress(b"a" * 1000))
    assert (len(data), full) == (10, True)
    assert decoder.feed(b"more") == (b"", True)


def test_gzip_bomb_limited() -> None:
    bomb = gzip.compress("<title>폭탄</title>".encode() + b"\0" * (50 * 1024 * 1024))
    server = site(http_response(bomb, headers=[("Content-Encoding", "gzip")]))
    started = time.monotonic()
    assert fetch(server, "https://site.example.test/") == "폭탄"
    assert time.monotonic() - started < 3


def test_total_timeout() -> None:
    server = site(http_response(html("<title>slow</title>")))
    server.delay = 5.0
    started = time.monotonic()
    assert fetch(server, "https://site.example.test/", total_timeout=0.3) is None
    assert time.monotonic() - started < 2


def test_slow_dns_counts_toward_timeout() -> None:
    server = site(http_response(html("<title>T</title>")))

    async def slow_resolve(host: str, port: int) -> list[str]:
        await asyncio.sleep(5)
        return [PUBLIC_IP]

    fetcher = PreviewFetcher(
        limits=FetchLimits(total_timeout=0.3), resolver=slow_resolve, backend_factory=server.backend
    )
    started = time.monotonic()
    assert asyncio.run(fetcher.fetch_title("https://site.example.test/")) is None
    assert time.monotonic() - started < 2


def test_concurrency_limited() -> None:
    server = StubServer(
        dns={"site.example.test": [PUBLIC_IP]},
        responses={PUBLIC_IP: [http_response(html(f"<title>{i}</title>")) for i in range(4)]},
    )
    server.delay = 0.02
    fetcher = make_fetcher(server, max_concurrent=2)

    async def run() -> list[str | None]:
        urls = [f"https://site.example.test/{i}" for i in range(4)]
        return await asyncio.gather(*(fetcher.fetch_title(u) for u in urls))

    results = asyncio.run(run())
    assert sorted(r or "" for r in results) == ["0", "1", "2", "3"]
    assert server.max_open == 2


def test_waiting_for_slot_respects_timeout() -> None:
    server = site(http_response(html("<title>T</title>")))
    fetcher = make_fetcher(server, max_concurrent=1, total_timeout=0.2)
    assert fetcher._slots.try_acquire()  # 자리를 모두 차지한 상태
    assert asyncio.run(fetcher.fetch_title("https://site.example.test/")) is None
    assert server.connections == []


def test_unresolvable_host() -> None:
    assert fetch(StubServer(), "https://nowhere.example.test/") is None


# ── 유튜브 oEmbed ───────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc123&t=10",
        "https://youtu.be/abc123",
        "https://m.youtube.com/watch?v=abc123",
    ],
)
def test_youtube_uses_oembed(url: str) -> None:
    payload = json.dumps({"title": "영상 &amp; 제목", "author_name": "x"}).encode()
    server = StubServer(
        dns={"www.youtube.com": [YOUTUBE_IP]},
        responses={YOUTUBE_IP: [http_response(payload, content_type="application/json")]},
    )
    assert fetch(server, url) == "영상 &amp; 제목"  # JSON 값은 HTML이 아니므로 그대로
    (conn,) = server.connections
    assert conn.sni == "www.youtube.com"
    request_line = conn.request.split(b"\r\n", 1)[0].decode()
    target = request_line.split(" ")[1]
    parts = urlsplit(target)
    assert parts.path == "/oembed"
    assert parse_qs(parts.query) == {"format": ["json"], "url": [url]}


def test_youtube_oembed_requires_json() -> None:
    server = StubServer(
        dns={"www.youtube.com": [YOUTUBE_IP]},
        responses={YOUTUBE_IP: [http_response(html("<title>HTML</title>"))]},
    )
    assert fetch(server, "https://youtu.be/abc") is None


def test_youtube_oembed_error_status() -> None:
    server = StubServer(
        dns={"www.youtube.com": [YOUTUBE_IP]},
        responses={
            YOUTUBE_IP: [http_response(b"Not Found", status=404, content_type="text/plain")]
        },
    )
    assert fetch(server, "https://youtu.be/private") is None


# ── API ─────────────────────────────────────────────


def test_preview_api(user: TestClient) -> None:
    server = StubServer(
        dns={"www.example.test": [PUBLIC_IP]},
        responses={
            PUBLIC_IP: [http_response(html('<meta property="og:title" content="미리보기">'))]
        },
    )
    user.app.state.preview_fetcher = make_fetcher(server)
    res = user.post("/api/meta/preview", json={"url": "  https://www.example.test/a "})
    assert res.status_code == 200
    assert res.json() == {"title": "미리보기", "source_id": 3}
    assert res.headers["cache-control"] == "no-store"


def test_preview_api_failure_is_200_null(user: TestClient) -> None:
    user.app.state.preview_fetcher = make_fetcher(StubServer())
    res = user.post("/api/meta/preview", json={"url": "https://youtu.be/abc"})
    assert res.status_code == 200
    assert res.json() == {"title": None, "source_id": 1}


def test_preview_api_private_address_200_null(user: TestClient) -> None:
    server = StubServer(responses={"127.0.0.1": [http_response(html("<title>secret</title>"))]})
    user.app.state.preview_fetcher = make_fetcher(server)
    res = user.post("/api/meta/preview", json={"url": "http://127.0.0.1:8000/"})
    assert res.status_code == 200
    assert res.json()["title"] is None
    assert server.connections == []


@pytest.mark.parametrize(
    "body",
    [
        {"url": "ftp://example.test/"},
        {"url": "file:///etc/passwd"},
        {"url": "javascript:alert(1)"},
        {"url": "gopher://example.test/"},
        {"url": "https://"},
        {"url": "https://example.test/" + "a" * 2048},
        {"url": ""},
        {},
        {"url": "https://example.test/", "extra": 1},
        {"url": "https://user:pw@example.test/"},
        {"url": "https://user@example.test/"},
        {"url": 1},
    ],
)
def test_preview_api_input_rules(user: TestClient, body: dict) -> None:
    server = StubServer()
    user.app.state.preview_fetcher = make_fetcher(server)
    res = user.post("/api/meta/preview", json=body)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_input"
    assert server.dns_queries == []


def test_preview_requires_session(client: TestClient) -> None:
    res = client.post("/api/meta/preview", json={"url": "https://example.test/"})
    assert res.status_code == 401


def test_preview_rate_limit_20_per_minute(user: TestClient, clock) -> None:
    user.app.state.preview_fetcher = make_fetcher(StubServer())
    body = {"url": "https://nowhere.example.test/"}
    for _ in range(20):
        assert user.post("/api/meta/preview", json=body).status_code == 200
    res = user.post("/api/meta/preview", json=body)
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "too_many_requests"
    assert 1 <= int(res.headers["retry-after"]) <= 60
    # 다른 API 에는 영향 없음
    assert user.get("/api/scraps").status_code == 200
    clock.advance(61)
    assert user.post("/api/meta/preview", json=body).status_code == 200


def test_preview_does_not_hold_db_connection(user: TestClient, monkeypatch) -> None:
    """가져오는 동안 DB 연결이 열려 있지 않다 (출처 판별 직후 닫힘)."""
    opened: list[object] = []
    database = user.app.state.db
    real_connect = database.connect

    def tracking_connect():
        conn = real_connect()
        opened.append(conn)
        return conn

    class CheckingFetcher:
        async def fetch_title(self, url: str) -> str | None:
            import sqlite3

            for conn in opened:
                with pytest.raises(sqlite3.ProgrammingError):
                    conn.execute("SELECT 1")  # 이미 닫힌 연결
            return "ok"

    monkeypatch.setattr(database, "connect", tracking_connect)
    user.app.state.preview_fetcher = CheckingFetcher()
    res = user.post("/api/meta/preview", json={"url": "https://example.test/"})
    assert res.json() == {"title": "ok", "source_id": 3}
    assert opened
