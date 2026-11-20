"""스크랩·출처·주제 API 공통 입력 검사 (docs/API.md v1.3 "공통", "스크랩 입력", "입력 규칙").

- 요청 본문 모델은 `StrictBody`를 상속한다: 정의되지 않은 필드가 있거나 타입이 다르면
  (`"1"` → 숫자, `1` → 불리언 같은 자동 변환 없이) 400 `invalid_input`.
- URL 검사(`validate_url`)는 스크랩 저장과 제목 미리보기(`/meta/preview`)가 같은 함수를 쓴다.
"""

import re
import unicodedata
from datetime import date
from typing import Annotated
from urllib.parse import SplitResult, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from app.errors import ApiError

SQLITE_MAX_INTEGER = 2**63 - 1
URL_MAX_LENGTH = 2048
NAME_MAX_LENGTH = 30
ALLOWED_URL_SCHEMES = frozenset({"http", "https"})

# 요청 본문의 id. 범위 밖 값은 SQLite 바인딩에서 OverflowError(500)가 나므로 검사 단계에서 400.
Id = Annotated[int, Field(ge=1, le=SQLITE_MAX_INTEGER)]

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def invalid_input(message: str = "입력값이 올바르지 않습니다.") -> ApiError:
    return ApiError(400, "invalid_input", message)


def not_found(message: str = "요청한 항목을 찾을 수 없습니다.") -> ApiError:
    return ApiError(404, "not_found", message)


def id_in_range(value: int) -> bool:
    return 1 <= value <= SQLITE_MAX_INTEGER


def _has_control_chars(value: str) -> bool:
    return any(unicodedata.category(ch) == "Cc" for ch in value)


# ── URL ─────────────────────────────────────────────


class InvalidUrlError(ValueError):
    """URL 규칙 위반. API에서는 400 `invalid_input`으로 바꾼다."""


def parse_url(raw: str) -> tuple[str, SplitResult]:
    """URL 규칙 검사 (스크랩 `url`, `/meta/preview`, 미리보기의 리다이렉트 대상 공통).

    앞뒤 공백 제거, 최대 2048자, http/https 스킴, 호스트 필수. 중간의 공백·제어문자, 사용자 정보
    (`user:pass@`, `user@`)도 받지 않는다.
    반환: (정리한 URL, 분해 결과). 위반하면 `InvalidUrlError`.
    """
    url = raw.strip()
    if not url or len(url) > URL_MAX_LENGTH:
        raise InvalidUrlError("length")
    if _has_control_chars(url) or any(ch.isspace() for ch in url):
        raise InvalidUrlError("characters")
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 — 잘못된 포트(범위 밖·숫자 아님)면 ValueError
    except ValueError as exc:
        raise InvalidUrlError("parse") from exc
    if parts.scheme.lower() not in ALLOWED_URL_SCHEMES:
        raise InvalidUrlError("scheme")
    if not parts.hostname:
        raise InvalidUrlError("host")
    if "@" in parts.netloc:
        raise InvalidUrlError("userinfo")
    return url, parts


def validate_url(raw: str) -> str:
    """API 입력용: 위반하면 400 `invalid_input`."""
    try:
        url, _ = parse_url(raw)
    except InvalidUrlError:
        raise invalid_input(
            "URL은 http:// 또는 https:// 로 시작하는 2048자 이하 주소여야 합니다"
            " (공백·사용자 정보 없이)."
        ) from None
    return url


def url_host(url: str) -> str:
    """출처 판별용 호스트: 소문자, 끝의 `.` 제거, 포트 없음."""
    host = urlsplit(url).hostname or ""
    return host.lower().rstrip(".")


# ── 이름·날짜 ────────────────────────────────────────


def clean_name(raw: str, what: str) -> tuple[str, str]:
    """출처·주제 이름: 앞뒤 공백 제거 후 1~30자, 제어문자 금지.

    반환: (저장할 이름, 중복 판정 키 — 대소문자 무시).
    """
    name = raw.strip()
    if not name or len(name) > NAME_MAX_LENGTH:
        raise invalid_input(f"{what} 이름은 1~{NAME_MAX_LENGTH}자로 입력해 주세요.")
    if _has_control_chars(name):
        raise invalid_input(f"{what} 이름에 사용할 수 없는 문자가 있습니다.")
    return name, name.casefold()


def validate_due_date(raw: str | None) -> str | None:
    """`YYYY-MM-DD` 실제 날짜 또는 None."""
    if raw is None:
        return None
    try:
        if not _DATE.match(raw):
            raise ValueError(raw)
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        raise invalid_input("마감일은 YYYY-MM-DD 형식의 날짜여야 합니다.") from None
