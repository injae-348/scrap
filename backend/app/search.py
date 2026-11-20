"""스크랩 검색어 `q` → SQL 조건 (docs/API.md v1.3 "검색 `q`").

- 공백으로 나눈 단어가 **모두** 들어 있는 스크랩 (최대 10단어, 200자, 제어문자 불가).
- 3글자 이상 단어: FTS5 trigram 색인(`scraps_fts MATCH`). 단어마다 큰따옴표로 감싸고 안의 `"`는
  두 번 써서, 사용자가 넣은 `*`·`OR`·`NEAR`·`:`·괄호 등이 FTS 문법으로 해석되지 않고 글자 그대로
  부분 일치한다.
- 1~2글자 단어: trigram 색인으로 찾을 수 없으므로 같은 표의 열을 LIKE 부분 문자열로 비교한다.
  `%`·`_`·`\\`는 이스케이프한다. (LIKE의 대소문자 무시는 ASCII 범위)
- 대상 열: 제목, 메모, URL, 주제 이름(트리거가 맞춰 두는 `scraps_fts.topics`).
"""

import unicodedata

from app.validation import invalid_input

Q_MAX_LENGTH = 200
Q_MAX_WORDS = 10
TRIGRAM_MIN_LENGTH = 3

_SHORT_WORD_SQL = (
    "s.id IN (SELECT rowid FROM scraps_fts"
    " WHERE title LIKE ? ESCAPE '\\' OR memo LIKE ? ESCAPE '\\'"
    " OR url LIKE ? ESCAPE '\\' OR topics LIKE ? ESCAPE '\\')"
)


def parse_query(raw: str | None) -> list[str]:
    """검색 단어 목록. 비어 있으면 []. 규칙 위반은 400."""
    if raw is None:
        return []
    q = unicodedata.normalize("NFC", raw.strip())
    if len(q) > Q_MAX_LENGTH:
        raise invalid_input(f"검색어는 {Q_MAX_LENGTH}자 이하로 입력해 주세요.")
    # NUL·줄바꿈·탭 등 제어문자는 받지 않는다 (FTS5 식은 NUL에서 끝나는 문자열로 처리된다).
    if any(unicodedata.category(ch) == "Cc" for ch in q):
        raise invalid_input("검색어에 사용할 수 없는 문자가 있습니다.")
    words = list(dict.fromkeys(q.split()))
    if len(words) > Q_MAX_WORDS:
        raise invalid_input(f"검색어는 최대 {Q_MAX_WORDS}단어까지 입력할 수 있습니다.")
    return words


def fts_phrase(word: str) -> str:
    """FTS5 문자열 리터럴로 인용 (안의 큰따옴표는 두 번)."""
    return '"' + word.replace('"', '""') + '"'


def like_pattern(word: str) -> str:
    escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_conditions(words: list[str]) -> tuple[list[str], list[object]]:
    """`scraps AS s`에 붙일 WHERE 조건과 매개변수."""
    clauses: list[str] = []
    params: list[object] = []
    long_words = [w for w in words if len(w) >= TRIGRAM_MIN_LENGTH]
    short_words = [w for w in words if len(w) < TRIGRAM_MIN_LENGTH]
    if long_words:
        clauses.append("s.id IN (SELECT rowid FROM scraps_fts WHERE scraps_fts MATCH ?)")
        params.append(" AND ".join(fts_phrase(w) for w in long_words))
    for word in short_words:
        clauses.append(_SHORT_WORD_SQL)
        params.extend([like_pattern(word)] * 4)
    return clauses, params
