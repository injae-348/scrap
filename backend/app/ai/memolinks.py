"""AI 채우기 메모의 링크 정리 (docs/API.md v1.6 "`memo` 링크 정리").

AI가 제안한 메모에서 마크다운 링크 문법을 걷어 내고, 링크였던 자리에는 글자와 실제 호스트만 남긴다.
사용자가 직접 쓴 메모(스크랩 저장)에는 쓰지 않는다.

| 입력 | 결과 |
|---|---|
| `[글자](주소)` (제목·꺾쇠 주소·괄호가 짝이 맞는 주소 포함) | `글자 (호스트)` |
| `![대체글](주소)`, `![대체글][이름]` | `대체글` (비면 지움) |
| `<https://…>` (꺾쇠 자동 링크) | `호스트` |
| `[이름]: 주소` (참조식 링크 정의 줄) | 줄째 지움 |
| `[글자][이름]`, `[글자][]` | `글자` |
| 맨 URL 텍스트 (`https://…`) | 그대로 |
| 그 밖에 남은 `[`·`]` | `\\[`·`\\]` (이스케이프) |

- 호스트: 주소에서 뽑은 호스트 이름을 소문자·ASCII(국제화 도메인은 퓨니코드)로. 주소가 http/https가
  아니거나 호스트를 뽑을 수 없으면 호스트 없이 `글자`만 남긴다 (꺾쇠 자동 링크는 꺾쇠 안 글자).
  주소의 역슬래시 이스케이프·문자 참조를 풀고 브라우저처럼 `\\`를 `/`로 보고 호스트를 뽑는다.
- 링크 글자 안의 링크·이미지도 같은 규칙으로 바꾼다 (안쪽부터).
- 코드 블록·인라인 코드·HTML 태그 안도 구분하지 않고 똑같이 다룬다.
- 바꾼 결과가 다시 링크 문법을 이루면(예: 빈 이미지를 지워 `]`와 `(`가 붙음) 최대 `MAX_PASSES`번
  다시 정리한다.
- **마지막에 남은 `[`·`]`를 모두 이스케이프한다.** 위 규칙으로 못 바꾼 모양(코드 스팬·HTML 속성 안의
  대괄호, 인용·목록 안의 참조 정의 등)이 있어도 결과에는 마크다운 링크·참조 문법이 남지 않는다.
- 처리량 상한: 입력은 앞 `INPUT_MAX_CHARS`자만 보고, 훑는 글자 수 합계가 `WORK_BUDGET`을 넘으면
  바꾸기를 멈추고 그 시점의 글에서 `[`·`]`만 이스케이프해 돌려준다
  (최악의 입력에서도 수십 ms 안).
"""

import html
import re
from urllib.parse import urlsplit

# 정리 전에 받는 메모 길이 상한. 결과는 2,000자로 자르므로 약간의 여유만 둔다.
INPUT_MAX_CHARS = 2_500
MAX_PASSES = 3
# 한 번의 정리에서 훑을 수 있는 글자 수 합계 (본 스캔 + 링크 뒷부분 살펴보기).
WORK_BUDGET = 60_000
_LABEL_MAX = 999
_DEST_MAX = 2_048
_PAREN_DEPTH_MAX = 32
_ASCII_PUNCT = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")

# 참조식 링크 정의 (CommonMark: 줄 앞 공백 0~3칸, 주소는 같은 줄이나 다음 줄, 제목은 선택).
# 공백 패턴은 서로 겹치지 않게 써서 되짚기(backtracking)가 늘지 않게 한다.
_DEFINITION = re.compile(
    r"^ {0,3}\[(?:[^\[\]\\]|\\.){1,999}\]:"
    r"[ \t]*(?:\n[ \t]*)?"
    r"(?:<(?:[^<>\n\\]|\\.)*>|[^\s<]\S*)"
    r"(?:(?:[ \t]+(?:\n[ \t]*)?|\n[ \t]*)"
    r"(?:\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|\((?:[^()\\]|\\.)*\)))?"
    r"[ \t]*(?:\n|\Z)",
    re.MULTILINE,
)
# 꺾쇠 자동 링크: URI(스킴 2~32자) 또는 이메일.
_AUTOLINK = re.compile(
    r"<([A-Za-z][A-Za-z0-9+.\-]{1,31}:[^\s<>\x00-\x1f]*"
    r"|[A-Za-z0-9.!#$%&'*+/=?^_`{|}~\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)*)>"
)
_BACKSLASH_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
_SPECIAL_SCHEME = re.compile(r"^(https?):[/]*", re.IGNORECASE)
_EDGE_CONTROL = re.compile(r"^[\x00-\x20]+|[\x00-\x20]+$")


class _OverBudget(Exception):
    pass


class _Work:
    """훑은 글자 수를 센다. 상한을 넘으면 `_OverBudget`."""

    def __init__(self, budget: int) -> None:
        self.left = budget

    def spend(self, amount: int) -> None:
        self.left -= amount
        if self.left < 0:
            raise _OverBudget


def strip_memo_links(text: str) -> str:
    """링크·이미지·자동 링크·참조식 정의를 걷어 내고 남은 대괄호를 이스케이프한다 (위 표)."""
    text = text[:INPUT_MAX_CHARS]
    work = _Work(WORK_BUDGET)
    try:
        for _ in range(MAX_PASSES):
            work.spend(len(text))
            cleaned = _rewrite_inline(_DEFINITION.sub("", text), work)
            if cleaned == text:
                break
            text = cleaned
    except _OverBudget:
        pass  # 마지막으로 끝낸 단계의 글을 이스케이프만 해서 돌려준다
    return escape_brackets(text)


def escape_brackets(text: str) -> str:
    """이스케이프되지 않은 `[`·`]`를 `\\[`·`\\]`로. 이미 있는 역슬래시 이스케이프는 그대로 둔다."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in _ASCII_PUNCT:
            out.append(text[i : i + 2])
            i += 2
            continue
        out.append("\\" + ch if ch in "[]" else ch)
        i += 1
    return "".join(out)


def link_host(destination: str) -> str | None:
    """링크 주소 → 소문자 ASCII 호스트. http/https가 아니거나 뽑을 수 없으면 None."""
    dest = html.unescape(_BACKSLASH_ESCAPE.sub(r"\1", destination))
    # 브라우저 URL 파서처럼 탭·줄바꿈을 지우고, 앞뒤 공백을 떼고, `\`를 `/`로 본다.
    dest = _EDGE_CONTROL.sub("", re.sub(r"[\t\n\r]", "", dest)).replace("\\", "/")
    match = _SPECIAL_SCHEME.match(dest)
    if match is None:
        return None
    dest = f"{match.group(1).lower()}://{dest[match.end() :]}"
    try:
        host = urlsplit(dest).hostname
    except ValueError:
        return None
    if not host:
        return None
    if host.isascii():
        ascii_host = host.lower()
    else:
        try:
            ascii_host = host.encode("idna").decode("ascii").lower()
        except UnicodeError:
            return None
    if not ascii_host or any(not ch.isprintable() or ch.isspace() for ch in ascii_host):
        return None
    if any(ch in ascii_host for ch in "/\\@?#%<>()[]"):
        return None
    return ascii_host


def _rewrite_inline(text: str, work: _Work) -> str:
    """한 번 훑으며 인라인 링크·이미지·참조 링크·자동 링크를 바꾼다.

    여는 `[`·`![`의 위치를 스택에 쌓고, `]`를 만나면 가장 가까운 여는 괄호와 짝지어 바로 뒤가
    `(주소)`나 `[이름]`인지 본다. 안쪽이 먼저 닫히므로 링크 글자 안의 링크는 먼저 바뀐다.
    """
    out: list[str] = []
    openers: list[tuple[int, bool]] = []  # (out 안의 위치, 이미지 여부)
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in _ASCII_PUNCT:
            out.append(text[i : i + 2])
            i += 2
            continue
        if ch == "!" and i + 1 < n and text[i + 1] == "[":
            openers.append((len(out), True))
            out.append("![")
            i += 2
            continue
        if ch == "[":
            openers.append((len(out), False))
            out.append("[")
            i += 1
            continue
        if ch == "]" and openers:
            start, image = openers.pop()
            tail = _parse_tail(text, i + 1, work)
            if tail is None:
                out.append("]")
                i += 1
                continue
            end, destination = tail
            work.spend(len(out) - start)
            label = "".join(out[start + 1 :])
            del out[start:]
            out.append(_render(label, destination, image))
            # 링크 안에 링크는 없다: 이 링크 바깥의 열린 `[`는 그대로 글자로 남는다.
            i = end
            continue
        if ch == "<":
            match = _AUTOLINK.match(text, i)
            work.spend(match.end() - i if match else 8)
            if match is not None:
                inner = match.group(1)
                host = link_host(inner) if ":" in inner else None
                out.append(host if host is not None else inner)
                i = match.end()
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _render(label: str, destination: str | None, image: bool) -> str:
    if image:
        return label.strip() and label
    host = link_host(destination) if destination is not None else None
    if host is None:
        return label
    if not label.strip():
        return host
    return f"{label} ({host})"


def _parse_tail(text: str, i: int, work: _Work) -> tuple[int, str | None] | None:
    """`]` 바로 뒤를 본다.

    `(주소 "제목")`이면 (끝 위치, 주소), `[이름]`이면 (끝 위치, None), 링크가 아니면 None.
    """
    n = len(text)
    if i >= n:
        return None
    if text[i] == "[":
        return _parse_reference(text, i, work)
    if text[i] != "(":
        return None
    j = _skip_space(text, i + 1)
    if j >= n:
        return None
    if text[j] == ")":
        return j + 1, ""
    dest = _parse_destination(text, j, work)
    if dest is None:
        return None
    j, destination = dest
    k = _skip_space(text, j)
    if k < n and k > j and text[k] in "\"'(":
        title_end = _parse_title(text, k, work)
        if title_end is not None:
            k = _skip_space(text, title_end)
    if k < n and text[k] == ")":
        return k + 1, destination
    return None


def _parse_reference(text: str, i: int, work: _Work) -> tuple[int, None] | None:
    """`[이름]` (빈 `[]` 포함). 이름에는 이스케이프되지 않은 대괄호가 없다."""
    j, n = i + 1, len(text)
    limit = min(n, i + 1 + _LABEL_MAX + 1)
    while j < limit:
        work.spend(1)
        ch = text[j]
        if ch == "\\" and j + 1 < n:
            j += 2
            continue
        if ch == "[":
            return None
        if ch == "]":
            return j + 1, None
        j += 1
    return None


def _skip_space(text: str, i: int) -> int:
    """공백·탭과 줄바꿈 하나까지 건너뛴다."""
    n = len(text)
    newline = False
    while i < n and text[i] in " \t\n":
        if text[i] == "\n":
            if newline:
                break
            newline = True
        i += 1
    return i


def _parse_destination(text: str, i: int, work: _Work) -> tuple[int, str] | None:
    """링크 주소. 길이 `_DEST_MAX`자·괄호 깊이 `_PAREN_DEPTH_MAX`를 넘으면 링크로 보지 않는다
    (그런 모양은 마지막 이스케이프로 무력화된다)."""
    n = min(len(text), i + _DEST_MAX + 2)
    if text[i] == "<":
        j = i + 1
        while j < n:
            work.spend(1)
            ch = text[j]
            if ch == "\\" and j + 1 < n:
                j += 2
                continue
            if ch in "\n<":
                return None
            if ch == ">":
                return j + 1, text[i + 1 : j]
            j += 1
        return None
    depth = 0
    j = i
    while j < n:
        work.spend(1)
        ch = text[j]
        if ch == "\\" and j + 1 < n and text[j + 1] in _ASCII_PUNCT:
            j += 2
            continue
        if ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F:
            break
        if ch == "(":
            depth += 1
            if depth > _PAREN_DEPTH_MAX:
                return None
        elif ch == ")":
            if depth == 0:
                break
            depth -= 1
        j += 1
    if j == i or depth != 0 or j - i > _DEST_MAX:
        return None
    return j, text[i:j]


def _parse_title(text: str, i: int, work: _Work) -> int | None:
    closing = ")" if text[i] == "(" else text[i]
    j, n = i + 1, len(text)
    while j < n:
        work.spend(1)
        ch = text[j]
        if ch == "\\" and j + 1 < n:
            j += 2
            continue
        if ch == closing:
            return j + 1
        if closing == ")" and ch == "(":
            return None
        if ch == "\n" and j + 1 < n and text[j + 1] == "\n":
            return None  # 빈 줄은 제목을 끝낸다
        j += 1
    return None
