"""출처 API `/api/sources` + 출처 자동 판별 (docs/API.md v1.3 "출처 자동 판별", "출처·주제 관리").

이 라우터는 세션 필수 상위 라우터(app/routing.py) 아래에 붙는다.
"""

import contextlib
import re
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import Field

from app.db import get_db, transaction
from app.errors import ApiError
from app.ordering import OrderBody, apply_order, next_sort_order
from app.validation import (
    StrictBody,
    clean_name,
    id_in_range,
    invalid_input,
    not_found,
    url_host,
)

router = APIRouter(prefix="/sources")

DbConn = Annotated[sqlite3.Connection, Depends(get_db)]

PATTERNS_MAX = 20
PATTERN_MAX_LENGTH = 253
# 호스트 이름: 영문 소문자·숫자·`-`로 된 라벨을 `.`로 이은 것 (빈 라벨·앞뒤 `.` 없음).
_PATTERN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*$")


class SourceCreate(StrictBody):
    name: str = Field(max_length=1000)
    domain_patterns: list[Annotated[str, Field(max_length=1000)]] = Field(
        default_factory=list, max_length=200
    )


class SourceUpdate(StrictBody):
    name: str | None = Field(default=None, max_length=1000)
    domain_patterns: list[Annotated[str, Field(max_length=1000)]] | None = Field(
        default=None, max_length=200
    )


# ── 판별 ────────────────────────────────────────────


def default_source_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM sources WHERE is_default = 1").fetchone()
    if row is None:  # 마이그레이션이 만들고 삭제를 막으므로 생기지 않는다
        raise RuntimeError("기본 출처가 없습니다.")
    return int(row["id"])


def host_matches(host: str, pattern: str) -> bool:
    return host == pattern or host.endswith("." + pattern)


def _host_forms(host: str) -> set[str]:
    """호스트와 그 ASCII(IDNA) 표기. 패턴은 ASCII만 받으므로 한글 도메인도 비교할 수 있게 한다."""
    forms = {host} if host else set()
    with contextlib.suppress(UnicodeError):
        forms.add(host.encode("idna").decode("ascii").lower())
    return forms


def detect_source_id(conn: sqlite3.Connection, url: str) -> int:
    """URL 호스트와 같거나 `.패턴`으로 끝나는 패턴 중 가장 긴 것의 출처. 없으면 기본 출처."""
    hosts = _host_forms(url_host(url))
    best: tuple[int, int] | None = None  # (패턴 길이, 출처 id)
    if hosts:
        for row in conn.execute("SELECT pattern, source_id FROM source_patterns"):
            pattern = row["pattern"]
            matched = any(host_matches(host, pattern) for host in hosts)
            if matched and (best is None or len(pattern) > best[0]):
                best = (len(pattern), int(row["source_id"]))
    return best[1] if best else default_source_id(conn)


# ── 조회 도우미 ──────────────────────────────────────


def _patterns_by_source(conn: sqlite3.Connection) -> dict[int, list[str]]:
    patterns: dict[int, list[str]] = {}
    for row in conn.execute(
        "SELECT source_id, pattern FROM source_patterns ORDER BY source_id, position"
    ):
        patterns.setdefault(int(row["source_id"]), []).append(row["pattern"])
    return patterns


def _to_json(row: sqlite3.Row, patterns: list[str]) -> dict[str, object]:
    return {
        "id": row["id"],
        "name": row["name"],
        "domain_patterns": patterns,
        "is_default": bool(row["is_default"]),
    }


def _load_source(conn: sqlite3.Connection, source_id: int) -> dict[str, object]:
    row = conn.execute(
        "SELECT id, name, is_default FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    if row is None:
        raise _source_not_found()
    return _to_json(row, _patterns_by_source(conn).get(source_id, []))


def _source_not_found() -> ApiError:
    return not_found("출처를 찾을 수 없습니다.")


def _clean_patterns(raw: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in raw:
        pattern = item.strip().lower()
        if not (1 <= len(pattern) <= PATTERN_MAX_LENGTH) or not _PATTERN.match(pattern):
            raise invalid_input(
                "도메인 패턴은 youtube.com 처럼 스킴·경로·포트 없는 호스트 이름이어야 합니다."
            )
        if pattern not in cleaned:
            cleaned.append(pattern)
    if len(cleaned) > PATTERNS_MAX:
        raise invalid_input(f"도메인 패턴은 출처당 최대 {PATTERNS_MAX}개입니다.")
    return cleaned


def _check_name_free(conn: sqlite3.Connection, key: str, own_id: int | None) -> None:
    row = conn.execute("SELECT id FROM sources WHERE name_key = ?", (key,)).fetchone()
    if row is not None and row["id"] != own_id:
        raise ApiError(400, "duplicate_name", "같은 이름의 출처가 이미 있습니다.")


def _check_patterns_free(conn: sqlite3.Connection, patterns: list[str], own_id: int | None) -> None:
    for pattern in patterns:
        row = conn.execute(
            "SELECT source_id FROM source_patterns WHERE pattern = ?", (pattern,)
        ).fetchone()
        if row is not None and row["source_id"] != own_id:
            raise ApiError(
                400, "duplicate_pattern", f"'{pattern}' 패턴은 이미 다른 출처에 있습니다."
            )


def _replace_patterns(conn: sqlite3.Connection, source_id: int, patterns: list[str]) -> None:
    conn.execute("DELETE FROM source_patterns WHERE source_id = ?", (source_id,))
    conn.executemany(
        "INSERT INTO source_patterns (pattern, source_id, position) VALUES (?, ?, ?)",
        [(pattern, source_id, i) for i, pattern in enumerate(patterns)],
    )


# ── 라우트 ──────────────────────────────────────────


@router.get("")
def list_sources(conn: DbConn) -> list[dict[str, object]]:
    patterns = _patterns_by_source(conn)
    rows = conn.execute(
        "SELECT id, name, is_default FROM sources ORDER BY sort_order, id"
    ).fetchall()
    return [_to_json(row, patterns.get(int(row["id"]), [])) for row in rows]


@router.post("", status_code=201)
def create_source(body: SourceCreate, conn: DbConn) -> dict[str, object]:
    name, key = clean_name(body.name, "출처")
    patterns = _clean_patterns(body.domain_patterns)
    with transaction(conn):
        _check_name_free(conn, key, None)
        _check_patterns_free(conn, patterns, None)
        cur = conn.execute(
            "INSERT INTO sources (name, name_key, is_default, sort_order) VALUES (?, ?, 0, ?)",
            (name, key, next_sort_order(conn, "sources")),
        )
        source_id = int(cur.lastrowid or 0)
        _replace_patterns(conn, source_id, patterns)
    return _load_source(conn, source_id)


# `/order`는 `/{source_id}`보다 먼저 등록한다.
@router.put("/order", status_code=204)
def order_sources(body: OrderBody, conn: DbConn) -> Response:
    apply_order(conn, "sources", body.ids)
    return Response(status_code=204)


@router.patch("/{source_id}")
def update_source(source_id: int, body: SourceUpdate, conn: DbConn) -> dict[str, object]:
    if not id_in_range(source_id):
        raise _source_not_found()
    fields = body.model_fields_set
    if "name" in fields and body.name is None:
        raise invalid_input("출처 이름을 입력해 주세요.")
    if "domain_patterns" in fields and body.domain_patterns is None:
        raise invalid_input("도메인 패턴은 배열이어야 합니다.")
    name_key = clean_name(body.name, "출처") if body.name is not None else None
    patterns = _clean_patterns(body.domain_patterns) if body.domain_patterns is not None else None

    with transaction(conn):
        row = conn.execute(
            "SELECT id, is_default FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if row is None:
            raise _source_not_found()
        if name_key is not None:
            _check_name_free(conn, name_key[1], source_id)
            conn.execute(
                "UPDATE sources SET name = ?, name_key = ? WHERE id = ?",
                (name_key[0], name_key[1], source_id),
            )
        if patterns is not None:
            if row["is_default"] and patterns:
                raise invalid_input("기본 출처에는 도메인 패턴을 넣을 수 없습니다.")
            _check_patterns_free(conn, patterns, source_id)
            _replace_patterns(conn, source_id, patterns)
    return _load_source(conn, source_id)


@router.delete("/{source_id}", status_code=204)
def delete_source(source_id: int, conn: DbConn) -> Response:
    if not id_in_range(source_id):
        raise _source_not_found()
    with transaction(conn):
        row = conn.execute(
            "SELECT id, is_default FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if row is None:
            raise _source_not_found()
        if row["is_default"]:
            raise ApiError(403, "default_source", "기본 출처는 삭제할 수 없습니다.")
        # 그 출처의 스크랩은 기본 출처로 옮긴다 (updated_at은 바꾸지 않는다).
        conn.execute(
            "UPDATE scraps SET source_id = ? WHERE source_id = ?",
            (default_source_id(conn), source_id),
        )
        conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    return Response(status_code=204)
