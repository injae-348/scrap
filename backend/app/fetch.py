"""사용자 URL 안전하게 가져오기 (공통 모듈, SSRF 방어).

사용자가 넣은 URL을 서버가 가져오는 기능(제목 미리보기 `app/preview.py`, AI 본문 추출
`app/pagetext.py`)은 **이 모듈의 `SafeFetcher`만** 쓴다. 다른 HTTP 클라이언트(httpx 기본 클라이언트,
trafilatura 내장 가져오기, urllib 등)로 사용자 URL을 가져오지 않는다.

규칙 (docs/API.md v1.3 "제목 미리보기", v1.5 "AI로 채우기")
- URL 검사는 스크랩 저장과 같은 함수(`app.validation.parse_url`): http/https, 2048자, 호스트 필수,
  사용자 정보 없음. 여기에 더해 포트는 80·443만 연결한다 (스크랩 저장은 포트 제한 없음).
- 호스트를 DNS로 풀어 **모든** 결과가 공인 주소일 때만 진행한다 (`app.netguard.is_public_ip`).
  연결은 검사한 IP로 직접 한다(`PinnedBackend`) → 검사와 연결 사이에 DNS 응답이 바뀌어도
  (DNS rebinding) 검사하지 않은 주소로 가지 않는다. https의 SNI·인증서 검증은 원래 호스트 이름으로
  한다 (httpcore가 URL의 호스트를 server_hostname으로 쓴다).
- 리다이렉트는 자동으로 따라가지 않고 직접 최대 5번, 매번 URL 검사 + DNS 검사를 다시 한다.
- 전체 시간 상한(`FetchLimits.total_timeout`, DNS·대기·모든 리다이렉트 포함).
  응답은 호출한 쪽이 고른 미디어 타입만, 본문은 앞부분 최대 1MB(압축 해제 후에도 1MB)까지만
  스트리밍으로 읽는다.
- 동시에 가져오는 수를 제한한다 (기본 2개). 자리가 나기를 기다리되 전체 제한 시간 안에서만.
- 환경변수 프록시를 쓰지 않고(httpcore 직접 사용), 쿠키·인증 정보를 보내지 않는다.
- TLS 설정(`SSLContext`, 인증서 묶음)은 프로세스에서 한 번만 만들어 재사용한다.
- 로그·예외 메시지에는 URL을 넣지 않는다.

공개 API
- `SafeFetcher(limits, resolver, backend_factory).fetch(url, accept) -> FetchResponse`
  (실패하면 `FETCH_FAILURES` 중 하나를 던진다)
- `FetchLimits`, `FetchResponse`, `FetchError`, `FETCH_FAILURES`
- `HTML_TYPES`, `JSON_TYPES`, `ALLOWED_PORTS`, `USER_AGENT`
- `decode_html(body, header_charset)`, `PinnedBackend`, `system_resolve`, `request_host(url)`
"""

import asyncio
import codecs
import functools
import re
import socket
import ssl
import threading
import zlib
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urljoin

import certifi
import httpcore

from app.netguard import is_public_ip, parse_ip
from app.validation import InvalidUrlError, parse_url

USER_AGENT = "Mozilla/5.0 (compatible; ScrapAppPreview/1.0)"
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
JSON_TYPES = frozenset({"application/json", "text/json"})
ALLOWED_PORTS = frozenset({80, 443})

Resolver = Callable[[str, int], Awaitable[list[str]]]
BackendFactory = Callable[[str, list[str]], httpcore.AsyncNetworkBackend]


@dataclass(frozen=True)
class FetchLimits:
    total_timeout: float = 5.0
    max_redirects: int = 5
    max_bytes: int = 1024 * 1024
    max_concurrent: int = 2


class FetchError(Exception):
    """가져오기 실패 (원인은 디버그용 짧은 문자열, URL은 넣지 않는다)."""


# 가져오기가 실패할 때 날 수 있는 예외. 호출한 쪽은 이것들을 "가져오지 못함"으로 처리한다.
FETCH_FAILURES: tuple[type[BaseException], ...] = (
    TimeoutError,
    FetchError,
    httpcore.TimeoutException,
    httpcore.NetworkError,
    httpcore.ProtocolError,
    ssl.SSLError,
    OSError,
    UnicodeError,
)


@dataclass(frozen=True)
class FetchResponse:
    headers: dict[str, str]  # 소문자 이름
    body: bytes  # 압축 해제 후 앞부분 최대 `max_bytes`
    media_type: str
    charset: str | None


@functools.cache
def shared_ssl_context() -> ssl.SSLContext:
    """인증서 묶음을 요청마다 읽지 않도록 한 번만 만든다 (CERT_REQUIRED + 호스트 이름 검증)."""
    return ssl.create_default_context(cafile=certifi.where())


# ── DNS·연결 ────────────────────────────────────────


async def system_resolve(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


class PinnedBackend(httpcore.AsyncNetworkBackend):
    """검사를 마친 IP로만 TCP 연결하는 네트워크 백엔드.

    httpcore가 넘기는 호스트 이름은 무시하고(다시 DNS를 풀지 않음) `ips`에 차례로 연결한다.
    TLS는 반환한 스트림에서 httpcore가 원래 호스트 이름(SNI·인증서 검증)으로 시작한다.
    """

    def __init__(
        self, host: str, ips: list[str], inner: httpcore.AsyncNetworkBackend | None = None
    ) -> None:
        self._host = host
        self._ips = ips
        self._inner = inner or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if host != self._host:
            raise httpcore.ConnectError("unexpected host")
        last: Exception = httpcore.ConnectError("no address")
        for ip in self._ips:
            try:
                return await self._inner.connect_tcp(
                    ip,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last = exc
        raise last

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("unix socket not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class FetchSlots:
    """동시 가져오기 수 제한. 이벤트 루프에 묶이지 않게 스레드 잠금 + 짧은 대기로 구현한다."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.in_use = 0
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        with self._lock:
            if self.in_use >= self.size:
                return False
            self.in_use += 1
            return True

    def release(self) -> None:
        with self._lock:
            self.in_use -= 1


# ── 요청 대상 ────────────────────────────────────────


@dataclass(frozen=True)
class Target:
    url: str
    scheme: str
    host: str  # DNS·SNI·Host 헤더용 ASCII 호스트 (IPv6는 대괄호 없이)
    port: int
    explicit_port: int | None
    target: str  # 경로 + 쿼리

    @property
    def url_host(self) -> str:
        return f"[{self.host}]" if ":" in self.host else self.host


# 경로·쿼리에 이미 있는 퍼센트 인코딩과 예약 문자는 그대로 두고, 나머지(공백·비ASCII)만 인코딩한다.
_SAFE_TARGET_CHARS = "/?#[]@!$&'()*+,;=:%-._~"


def parse_target(url: str) -> Target:
    """URL 검사 + 연결 대상. 규칙 위반(스킴·포트·호스트 등)이면 `FetchError`."""
    try:
        clean, parts = parse_url(url)
    except InvalidUrlError as exc:
        raise FetchError("invalid url") from exc
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").rstrip(".")
    if parse_ip(hostname) is None:
        try:
            hostname = hostname.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise FetchError("bad host") from exc
    if not hostname:
        raise FetchError("bad host")
    explicit_port = parts.port
    port = explicit_port or (443 if scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise FetchError("port not allowed")
    path = parts.path or "/"
    target = quote(path, safe=_SAFE_TARGET_CHARS)
    if parts.query:
        target += "?" + quote(parts.query, safe=_SAFE_TARGET_CHARS)
    return Target(clean, scheme, hostname.lower(), port, explicit_port, target)


def request_host(url: str) -> str:
    """가져올 호스트 이름(소문자 ASCII). URL 규칙 위반이면 `FetchError`."""
    return parse_target(url).host


# ── 본문 해석 ────────────────────────────────────────


def media_type(headers: dict[str, str]) -> tuple[str, str | None]:
    """Content-Type → (미디어 타입 소문자, charset 또는 None)."""
    value = headers.get("content-type", "")
    media = value.split(";", 1)[0].strip().lower()
    match = re.search(r"charset\s*=\s*[\"']?([A-Za-z0-9_.:-]+)", value, re.IGNORECASE)
    return media, match.group(1) if match else None


_META_CHARSET = re.compile(rb"<meta[^>]{0,512}?charset\s*=\s*[\"']?\s*([A-Za-z0-9_.:-]+)", re.I)


def _normalize_charset(name: str) -> str:
    lowered = name.strip().lower()
    # 웹 호환(WHATWG 인코딩 표준): EUC-KR 계열은 상위 집합 cp949, latin-1 계열은 windows-1252.
    if lowered in {"euc-kr", "euc_kr", "ks_c_5601-1987", "ks_c_5601", "korean", "windows-949"}:
        return "cp949"
    if lowered in {"iso-8859-1", "latin1", "latin-1", "us-ascii", "ascii"}:
        return "cp1252"
    return lowered


def decode_html(body: bytes, header_charset: str | None) -> str:
    """BOM → Content-Type charset → `<meta charset>` → UTF-8 순서로 문자셋을 정한다."""
    for bom, enc in (
        (codecs.BOM_UTF8, "utf-8"),
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
    ):
        if body.startswith(bom):
            return body[len(bom) :].decode(enc, errors="replace")
    candidates: list[str] = []
    if header_charset:
        candidates.append(header_charset)
    match = _META_CHARSET.search(body[:4096])
    if match:
        meta = match.group(1).decode("ascii", "replace")
        # 본문에 적힌 utf-16 선언은 무시한다 (HTML 표준: ASCII 호환 문서에서 utf-16 meta → utf-8).
        if not meta.lower().startswith("utf-16"):
            candidates.append(meta)
    for name in candidates:
        try:
            return body.decode(_normalize_charset(name), errors="replace")
        except LookupError:
            continue
    return body.decode("utf-8", errors="replace")


class BodyDecoder:
    """Content-Encoding(gzip/deflate) 해제. 해제 후 크기도 `limit`까지만 만든다."""

    def __init__(self, encoding: str, limit: int) -> None:
        enc = encoding.strip().lower()
        if enc in ("", "identity"):
            self._obj = None
        elif enc in ("gzip", "x-gzip", "deflate"):
            # 32 + MAX_WBITS: gzip·zlib 머리말을 자동 판별
            self._obj = zlib.decompressobj(32 + zlib.MAX_WBITS)
        else:
            raise FetchError("unsupported encoding")
        self.limit = limit
        self.size = 0

    def feed(self, chunk: bytes) -> tuple[bytes, bool]:
        """(해제한 조각, 상한 도달 여부)."""
        remaining = self.limit - self.size
        if remaining <= 0:
            # zlib 은 max_length=0 을 "제한 없음"으로 보므로 여기서 먼저 끊는다.
            return b"", True
        if self._obj is None:
            data = chunk[:remaining]
            full = len(chunk) >= remaining
        else:
            try:
                data = self._obj.decompress(chunk, remaining)
            except zlib.error as exc:
                raise FetchError("bad compression") from exc
            full = bool(self._obj.unconsumed_tail) or len(data) >= remaining
        self.size += len(data)
        return data, full


# ── 가져오기 ────────────────────────────────────────


class SafeFetcher:
    """사용자 URL을 가져오는 유일한 통로. 기능마다 하나씩 만든다 (동시 가져오기 자리는 인스턴스별).

    테스트는 `resolver`(DNS)와 `backend_factory`(TCP 연결)를 바꿔 네트워크 없이 검사한다.
    """

    def __init__(
        self,
        limits: FetchLimits | None = None,
        resolver: Resolver | None = None,
        backend_factory: BackendFactory | None = None,
    ) -> None:
        self.limits = limits or FetchLimits()
        self._resolve = resolver or system_resolve
        self._backend_factory = backend_factory or (lambda host, ips: PinnedBackend(host, ips))
        self.slots = FetchSlots(self.limits.max_concurrent)
        self.ssl_context = shared_ssl_context()

    async def fetch(self, url: str, accept: frozenset[str]) -> FetchResponse:
        """`url`을 가져온다 (자리 대기·DNS·리다이렉트 포함 전체 `total_timeout` 안에서).

        200 응답이고 미디어 타입이 `accept`에 있을 때만 성공. 실패는 `FETCH_FAILURES` 중 하나.
        """
        async with asyncio.timeout(self.limits.total_timeout), self._slot():
            return await self._get(url, accept)

    @asynccontextmanager
    async def _slot(self) -> AsyncIterator[None]:
        while not self.slots.try_acquire():
            await asyncio.sleep(0.05)  # 바깥의 전체 제한 시간 안에서만 기다린다
        try:
            yield
        finally:
            self.slots.release()

    async def _get(self, url: str, accept: frozenset[str]) -> FetchResponse:
        current = url
        for _ in range(self.limits.max_redirects + 1):
            target = parse_target(current)
            ips = await self._public_ips(target)
            status, headers, body = await self._request(target, ips, accept)
            if status in REDIRECT_STATUSES:
                location = headers.get("location")
                if not location:
                    raise FetchError("redirect without location")
                current = urljoin(target.url, location.strip())
                continue
            if status != 200:
                raise FetchError(f"status {status}")
            media, charset = media_type(headers)
            return FetchResponse(headers=headers, body=body, media_type=media, charset=charset)
        raise FetchError("too many redirects")

    async def _public_ips(self, target: Target) -> list[str]:
        literal = parse_ip(target.host)
        if literal is not None:
            addresses = [literal]
        else:
            resolved = await self._resolve(target.host, target.port)
            addresses = [ip for ip in (parse_ip(r) for r in resolved) if ip is not None]
            if len(addresses) != len(resolved):
                raise FetchError("unparsable address")
        if not addresses:
            raise FetchError("no address")
        if not all(is_public_ip(ip) for ip in addresses):
            raise FetchError("non-public address")
        # IPv4 먼저 (서버에 IPv6 경로가 없을 수 있다). 중복 제거.
        ordered = sorted(dict.fromkeys(addresses), key=lambda ip: ip.version)
        return [str(ip) for ip in ordered]

    async def _request(
        self, target: Target, ips: list[str], accept: frozenset[str]
    ) -> tuple[int, dict[str, str], bytes]:
        limit = self.limits.max_bytes
        timeout = self.limits.total_timeout
        pool = httpcore.AsyncConnectionPool(
            ssl_context=self.ssl_context,
            network_backend=self._backend_factory(target.url_host, ips),
            max_connections=1,
            retries=0,
        )
        request_url = httpcore.URL(
            scheme=target.scheme.encode("ascii"),
            host=target.url_host.encode("ascii"),
            port=target.explicit_port,
            target=target.target.encode("ascii"),
        )
        request_headers = [
            (b"User-Agent", USER_AGENT.encode("ascii")),
            (b"Accept", b"text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.1"),
            (b"Accept-Language", b"ko,en;q=0.8"),
            (b"Accept-Encoding", b"gzip, deflate"),
        ]
        extensions = {
            "timeout": {"connect": timeout, "read": timeout, "write": timeout, "pool": timeout},
            # SNI·인증서 검증은 원래 호스트 이름으로 (IP 주소 URL이면 IP로 검증된다).
            "sni_hostname": target.host,
        }
        async with (
            pool,
            pool.stream("GET", request_url, headers=request_headers, extensions=extensions) as resp,
        ):
            headers = {
                k.decode("latin-1").lower(): v.decode("latin-1").strip() for k, v in resp.headers
            }
            if resp.status != 200:
                return resp.status, headers, b""  # 리다이렉트·오류는 본문을 읽지 않는다
            media, _ = media_type(headers)
            if media not in accept:
                raise FetchError("unexpected content type")
            decoder = BodyDecoder(headers.get("content-encoding", ""), limit)
            parts: list[bytes] = []
            raw_size = 0
            async for chunk in resp.aiter_stream():
                raw_size += len(chunk)
                data, full = decoder.feed(chunk)
                parts.append(data)
                if full or raw_size >= limit:
                    break  # 앞부분 1MB만 쓴다. 나머지는 읽지 않고 연결을 닫는다.
            return resp.status, headers, b"".join(parts)
