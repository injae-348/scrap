"""AI 메모 링크 정리 (docs/API.md v1.6 "`memo` 링크 정리"). 링크·주소는 모두 가짜 도메인."""

import re
import time

import pytest

from app.ai.memolinks import INPUT_MAX_CHARS, link_host, strip_memo_links
from app.ai.router import MEMO_MAX_CHARS, _clean_memo


@pytest.mark.parametrize(
    ("memo", "expected"),
    [
        # 일반 링크 → 글자 (호스트), 호스트는 소문자
        (
            "요약 [공식 문서](https://Docs.Example.test/a?b=1#x) 참고",
            "요약 공식 문서 (docs.example.test) 참고",
        ),
        ("[a](http://ex.test:8080/p)", "a (ex.test)"),
        # 제목이 붙은 링크, 꺾쇠로 감싼 주소
        ("[a](https://t.test \"제목\") [b](<https://u.test/a b> 't')", "a (t.test) b (u.test)"),
        ("[a](https://t.test (제목))", "a (t.test)"),
        # 괄호가 짝이 맞는 주소 (중첩 괄호)
        ("[위키](https://w.test/a_(b_(c))_d) 끝", "위키 (w.test) 끝"),
        # 이미지 → 대체글, 비면 지움
        ("앞 ![그림](https://img.test/x.png) 뒤", "앞 그림 뒤"),
        ("앞 ![](https://img.test/x.png) 뒤", "앞  뒤"),
        ("![  ](https://img.test/x.png)", ""),
        ("![참조 그림][img]", "참조 그림"),
        # 링크 안의 이미지 (안쪽부터)
        ("[![로고](https://i.test/l.png)](https://site.test)", "로고 (site.test)"),
        # 꺾쇠 자동 링크 → 호스트
        ("링크 <https://Ex.Test/path?q=1>", "링크 ex.test"),
        ("<http://ex.test>", "ex.test"),
        # 참조식: 정의 줄은 지우고, 참조는 글자만
        ('본문 [글자][r] 끝\n\n[r]: https://evil.test "t"\n', "본문 글자 끝\n\n"),
        ("[글자][] 와 [x][Y]", "글자 와 x"),
        ("앞\n   [r]: <https://evil.test>\n뒤", "앞\n뒤"),
        ("앞\n[r]:\n  https://evil.test\n  'title'\n뒤", "앞\n뒤"),
        # 정의 형식이 아닌 줄(주소 뒤에 다른 글)은 남긴다
        ("[참고]: 이 글은 좋다", "\\[참고\\]: 이 글은 좋다"),
        # http/https 가 아닌 주소 → 글자만
        ("[클릭](javascript:alert(1))", "클릭"),
        ("[파일](ftp://f.test/a) [메일](mailto:a@b.test)", "파일 메일"),
        ("[상대](/path/x) [빈]()", "상대 빈"),
        ("<mailto:a@b.test> <a@b.test> <ftp://f.test>", "mailto:a@b.test a@b.test ftp://f.test"),
        # 호스트를 뽑을 수 없음 → 글자만
        ("[x](https://) [y](https://[bad/)", "x y"),
        # 브라우저처럼 http(s) 뒤의 슬래시 개수는 따지지 않는다
        ("[z](https:///path)", "z (path)"),
        # 맨 URL 텍스트는 그대로
        ("맨 https://bare.test/x?y=1 그대로", "맨 https://bare.test/x?y=1 그대로"),
        ("www.bare.test 도 그대로", "www.bare.test 도 그대로"),
        # 링크가 아닌 대괄호·꺾쇠
        # 링크가 아닌 대괄호는 이스케이프한다 (렌더링하면 그대로 `[중요]`)
        ("[중요] 마감 <b> a<b", "\\[중요\\] 마감 <b> a<b"),
        ("\\[아님\\](https://x.test)", "\\[아님\\](https://x.test)"),
        # 코드 블록·인라인 코드 안도 똑같이 바꾼다 (문서화한 판단)
        ("`[c](https://code.test)`", "`c (code.test)`"),
        ("```\n[c](https://code.test)\n```", "```\nc (code.test)\n```"),
    ],
)
def test_strip_rules(memo: str, expected: str) -> None:
    assert strip_memo_links(memo) == expected


@pytest.mark.parametrize(
    ("destination", "host"),
    [
        ("https://Good.Test/a", "good.test"),
        ("https://good.test@evil.test/", "evil.test"),  # 사용자 정보 뒤가 실제 호스트
        ("https://good.test\\@evil.test/", "evil.test"),  # 역슬래시 이스케이프를 푼다
        ("https://evil.test\\good.test", "evil.test"),  # 브라우저처럼 \ 를 / 로
        ("https:evil.test/x", "evil.test"),  # 슬래시 없는 http(s)
        ("HTTPS:////evil.test", "evil.test"),
        ("https://ev&#105;l.test", "evil.test"),  # 문자 참조
        ("https://gооgle.test/", "xn--ggle-55da.test"),  # 국제화 도메인 → 퓨니코드
        ("https://[::1]/", "::1"),
        ("javascript:alert(1)", None),
        ("//evil.test/x", None),
        ("https://", None),
        ("https://[bad/", None),
        ("https://%65vil.test", None),
    ],
)
def test_link_host(destination: str, host: str | None) -> None:
    assert link_host(destination) == host


# 이스케이프되지 않은 `[`·`]` (앞의 역슬래시가 짝수 개) 또는 꺾쇠 자동 링크
_LIVE_SYNTAX = re.compile(r"(?<!\\)(?:\\\\)*[\[\]]|<[A-Za-z][A-Za-z0-9+.\-]{1,31}:")


def assert_no_link_syntax(text: str) -> None:
    assert not _LIVE_SYNTAX.search(text), text


def test_no_link_syntax_survives_tricky_inputs() -> None:
    inputs = [
        # 빈 이미지를 지우면 `[t](주소)`가 새로 생긴다 → 다시 정리
        "[t]![](x)(https://evil.test)",
        "[[[[a](https://a.test)](https://b.test)](https://c.test)](https://d.test)",
        "[바깥 [안쪽](https://in.test) 글](https://out.test)",
        "[a](<https://e.test>) [b]( https://f.test\n 'x' )",
        "[t]![](x)![](y)(https://g.test)" * 3,
        # 코드 스팬·HTML 속성 안의 대괄호 (렌더러는 이것을 링크로 본다)
        "[a`]`](https://evil.example)",
        '[a<x y="]">](https://evil.example)',
        # 인용·목록 안의 참조 정의 + 단축 참조
        "> [x]: https://evil.example\n>\n> [x]",
        "- [x]: https://evil.example\n\n[x] 를 보세요",
        "[x]\n\n* [x]: https://evil.example",
        # 이스케이프된 역슬래시 뒤의 대괄호는 살아 있는 대괄호다
        "\\\\[a\\\\](https://evil.example)",
    ]
    for text in inputs:
        assert_no_link_syntax(strip_memo_links(text))
    assert strip_memo_links(inputs[0]) == "t (evil.test)"
    assert strip_memo_links(inputs[2]) == "바깥 안쪽 (in.test) 글 (out.test)"
    assert strip_memo_links(inputs[5]) == "\\[a`\\]`\\](https://evil.example)"


def test_plain_text_only_gets_brackets_escaped() -> None:
    text = "- 대학생 대상\n- 상금 100만 원 (1등)\n- 신청: 2027-01-22까지 [필수]"
    assert strip_memo_links(text) == text.replace("[필수]", "\\[필수\\]")
    # 두 번 적용해도 같다 (이미 있는 이스케이프는 그대로)
    assert strip_memo_links(strip_memo_links(text)) == strip_memo_links(text)


# 최악의 입력 (긴 반복·깊은 괄호·닫히지 않는 주소·제목·공백 등).
# 모두 결과에 링크 문법이 없어야 한다.
WORST_INPUTS = {
    "empty-link-open": "[](" * 2000,
    "images-then-open": "![](x)" * 200 + "[](" * 2000,
    "link-open": "[a](" * 3000,
    "brackets": "[" * 9000,
    "join-chain": "[x]![](" * 1500,
    "close-open": "](" * 5000,
    "deep-parens": "[x](" + "(" * 3000,
    "open-title": '[x](a "' + "x" * 3000,
    "references": "[x][" * 2000,
    "autolink-ish": "<a:" * 3000,
    "email-ish": "<" + "a" * 3000 + "@",
    "definition-spaces": "[a]:" + " " * 3000 + "x",
    "definition-lines": "[a]: b\n" * 600,
    "definition-newlines": ("[a]:" + " " * 50 + "\n" + " " * 50) * 40,
    "nested-links": "[" * 600 + "a" + "](https://a.test)" * 600,
}


@pytest.mark.parametrize("name", list(WORST_INPUTS))
def test_worst_case_inputs_are_fast(name: str) -> None:
    text = WORST_INPUTS[name]
    # 측정값(개발 PC): 입력마다 1회 10 ms 안팎. CI 편차를 감안해 상한은 넉넉히 둔다.
    best = min(_timed(text) for _ in range(3))
    assert best < 0.15, f"{name}: {best * 1000:.1f} ms"
    result = strip_memo_links(text)
    assert_no_link_syntax(result)
    assert len(_clean_memo(text) or "") <= MEMO_MAX_CHARS


def _timed(text: str) -> float:
    start = time.perf_counter()
    strip_memo_links(text)
    _clean_memo(text)
    return time.perf_counter() - start


def test_many_real_links_are_all_converted() -> None:
    # 정상 범위의 링크가 많아도 처리량 상한에 걸리지 않고 모두 바뀐다.
    line = "- [신청 안내](https://apply.example.test/form?x=1) 마감\n"
    memo = line * (INPUT_MAX_CHARS // len(line))
    cleaned = strip_memo_links(memo)
    assert cleaned.count("신청 안내 (apply.example.test)") == INPUT_MAX_CHARS // len(line)
    assert "\\[" not in cleaned


def test_clean_memo_strips_links_before_truncating() -> None:
    # 링크를 정리하면 2,000자 안에 들어오는 글: 자르기 전에 정리해야 뒤쪽 글이 남는다.
    link = "[글](https://example.test/" + "p" * 80 + ") "
    memo = link * 20 + "끝부분"
    assert MEMO_MAX_CHARS < len(memo) <= INPUT_MAX_CHARS
    cleaned = _clean_memo(memo)
    assert cleaned is not None and cleaned.endswith("끝부분")
    assert "](" not in cleaned


def test_clean_memo_truncation_cannot_create_definition() -> None:
    # 정의 줄이 아닌 줄(주소 뒤에 글)을 자르면 정의 줄 모양이 되지만, 대괄호가 이스케이프돼 있다.
    tail = "\n[r]: https://evil.test"
    memo = "가" * (MEMO_MAX_CHARS - len(tail) - 2) + tail + " 그리고 더 많은 설명"
    cleaned = _clean_memo(memo)
    assert cleaned is not None and len(cleaned) == MEMO_MAX_CHARS
    assert cleaned.endswith("\n\\[r\\]: https://evil.test")
    assert_no_link_syntax(cleaned)


def test_clean_memo_drops_half_escape_at_cut() -> None:
    memo = "가" * (MEMO_MAX_CHARS - 1) + "[중요]"
    cleaned = _clean_memo(memo)
    assert cleaned == "가" * (MEMO_MAX_CHARS - 1)
