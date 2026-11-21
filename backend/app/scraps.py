"""스크랩 API `/api/scraps` (docs/API.md "스크랩", v1.3 "스크랩 입력", "스크랩 목록", "검색").

목록 항목은 v1.4 `ScrapListItem` (메모 대신 `memo_preview`).

이 라우터는 세션 필수 상위 라우터(app/routing.py) 아래에 붙는다.
검색 색인(scraps_fts)은 DB 트리거가 스크랩·주제 변경과 함께 맞춘다 (0003_scraps.sql).
"""

import base64
import binascii
import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field

from app.clock import KST, Clock, to_iso
from app.db import get_db, transaction
from app.search import parse_query, search_conditions
from app.sources import detect_source_id
from app.validation import (
    Id,
    StrictBody,
    id_in_range,
    invalid_input,
    not_found,
    validate_due_date,
    validate_url,
)

router = APIRouter(prefix="/scraps")
logger = logging.getLogger("app")

DbConn = Annotated[sqlite3.Connection, Depends(get_db)]

TITLE_MAX_LENGTH = 300
MEMO_MAX_LENGTH = 100_000
TOPICS_MAX = 20
LIMIT_DEFAULT = 30
LIMIT_MAX = 100
DUE_UPCOMING_DAYS = 7
# 요청 본문 필드의 절대 상한 (규칙상 상한보다 넉넉하게 — 넘으면 일반 400).
_RAW_TEXT_MAX = 1_000_000
_RAW_LIST_MAX = 200
_FILTER_IDS_MAX = 100
_INT_TEXT = re.compile(r"^-?[0-9]{1,40}$")


class ScrapCreate(StrictBody):
    url: str = Field(max_length=_RAW_TEXT_MAX)
    title: str | None = Field(default=None, max_length=_RAW_TEXT_MAX)
    memo: str = Field(default="", max_length=_RAW_TEXT_MAX)
    source_id: Id | None = None
    topic_ids: list[Id] = Field(default_factory=list, max_length=_RAW_LIST_MAX)
    due_date: str | None = Field(default=None, max_length=100)
    liked: bool = False


class ScrapUpdate(StrictBody):
    # `liked`가 없으므로 보내면 400 (좋아요는 PUT /like 로만).
    url: str | None = Field(default=None, max_length=_RAW_TEXT_MAX)
    title: str | None = Field(default=None, max_length=_RAW_TEXT_MAX)
    memo: str | None = Field(default=None, max_length=_RAW_TEXT_MAX)
    source_id: Id | None = None
    topic_ids: list[Id] | None = Field(default=None, max_length=_RAW_LIST_MAX)
    due_date: str | None = Field(default=None, max_length=100)


class LikeBody(StrictBody):
    liked: bool


# ── 입력 정리 ────────────────────────────────────────


def _clean_title(raw: str | None, url: str) -> str:
    title = (raw or "").strip()
    if not title:
        return url
    if len(title) > TITLE_MAX_LENGTH:
        raise invalid_input(f"제목은 {TITLE_MAX_LENGTH}자 이하로 입력해 주세요.")
    return title


def _check_memo(memo: str) -> str:
    if len(memo) > MEMO_MAX_LENGTH:
        raise invalid_input(f"메모는 {MEMO_MAX_LENGTH:,}자 이하로 입력해 주세요.")
    return memo


def _clean_topic_ids(conn: sqlite3.Connection, raw: list[int]) -> list[int]:
    ids = list(dict.fromkeys(raw))
    if len(ids) > TOPICS_MAX:
        raise invalid_input(f"주제는 스크랩당 최대 {TOPICS_MAX}개까지 고를 수 있습니다.")
    if ids:
        marks = ",".join("?" * len(ids))
        found = conn.execute(
            f"SELECT count(*) FROM topics WHERE id IN ({marks})",  # noqa: S608
            ids,
        ).fetchone()[0]
        if found != len(ids):
            raise invalid_input("없는 주제가 포함되어 있습니다.")
    return ids


def _check_source(conn: sqlite3.Connection, source_id: int) -> int:
    if conn.execute("SELECT 1 FROM sources WHERE id = ?", (source_id,)).fetchone() is None:
        raise invalid_input("없는 출처입니다.")
    return source_id


def _set_topics(conn: sqlite3.Connection, scrap_id: int, topic_ids: list[int]) -> None:
    conn.execute("DELETE FROM scrap_topics WHERE scrap_id = ?", (scrap_id,))
    conn.executemany(
        "INSERT INTO scrap_topics (scrap_id, topic_id) VALUES (?, ?)",
        [(scrap_id, topic_id) for topic_id in topic_ids],
    )


def _now_iso(request: Request) -> str:
    clock: Clock = request.app.state.clock
    return to_iso(clock.now())


def _scrap_not_found() -> Exception:
    return not_found("스크랩을 찾을 수 없습니다.")


# ── 응답 만들기 ──────────────────────────────────────

MEMO_PREVIEW_LENGTH = 300

_COMMON_COLUMNS = (
    "s.id, s.url, s.title, s.liked, s.due_date, s.created_at, s.updated_at,"
    " s.source_id, src.name AS source_name"
)
# 상세·생성·수정: 메모 전문.
_SCRAP_COLUMNS = f"{_COMMON_COLUMNS}, s.memo"
# 목록(ScrapListItem, v1.4): 메모 앞부분만 SQL에서 잘라 온다.
# SQLite substr()은 TEXT를 바이트가 아닌 문자 단위로 센다.
_LIST_COLUMNS = f"{_COMMON_COLUMNS}, substr(s.memo, 1, {MEMO_PREVIEW_LENGTH}) AS memo_preview"


def _serialize(
    conn: sqlite3.Connection, rows: list[sqlite3.Row], *, preview: bool = False
) -> list[dict[str, object]]:
    """스크랩 행 → API 형식. 주제는 주제의 사용자 지정 순서로 붙인다.

    `preview=True`(목록)이면 `memo` 대신 `memo_preview`를 넣는다 (행은 `_LIST_COLUMNS`로 읽는다).
    """
    memo_key = "memo_preview" if preview else "memo"
    topics: dict[int, list[dict[str, object]]] = {int(r["id"]): [] for r in rows}
    if rows:
        marks = ",".join("?" * len(rows))
        # 자리표시자(?)만 이어 붙인다.
        for t in conn.execute(
            "SELECT st.scrap_id, t.id, t.name FROM scrap_topics st"  # noqa: S608
            " JOIN topics t ON t.id = st.topic_id"
            f" WHERE st.scrap_id IN ({marks}) ORDER BY t.sort_order, t.id",
            list(topics),
        ):
            topics[int(t["scrap_id"])].append({"id": t["id"], "name": t["name"]})
    return [
        {
            "id": r["id"],
            "url": r["url"],
            "title": r["title"],
            memo_key: r[memo_key],
            "source": {"id": r["source_id"], "name": r["source_name"]},
            "topics": topics[int(r["id"])],
            "liked": bool(r["liked"]),
            "due_date": r["due_date"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def _load_scrap(conn: sqlite3.Connection, scrap_id: int) -> dict[str, object]:
    row = conn.execute(
        f"SELECT {_SCRAP_COLUMNS} FROM scraps s JOIN sources src ON src.id = s.source_id"  # noqa: S608
        " WHERE s.id = ?",
        (scrap_id,),
    ).fetchone()
    if row is None:
        raise _scrap_not_found()
    return _serialize(conn, [row])[0]


def search_list_items(
    conn: sqlite3.Connection, words: list[str], limit: int
) -> list[dict[str, object]]:
    """검색어 단어(`parse_query` 결과)로 찾은 `ScrapListItem` 최신순 최대 `limit`개.

    목록 `GET /scraps?q=`와 같은 검색 조건(`search_conditions`)을 쓴다 (AI 검색 도구용).
    """
    clauses, params = search_conditions(words)
    sql = (
        f"SELECT {_LIST_COLUMNS} FROM scraps s JOIN sources src ON src.id = s.source_id"  # noqa: S608
        + (" WHERE " + " AND ".join(clauses) if clauses else "")
        + " ORDER BY s.created_at DESC, s.id DESC LIMIT ?"
    )
    rows = conn.execute(sql, [*params, limit]).fetchall()
    return _serialize(conn, rows, preview=True)


def list_items_by_id(conn: sqlite3.Connection, ids: list[int]) -> dict[int, dict[str, object]]:
    """id → `ScrapListItem`. 없는(지워진) id는 빠진다."""
    ids = [i for i in dict.fromkeys(ids) if id_in_range(i)]
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT {_LIST_COLUMNS} FROM scraps s JOIN sources src ON src.id = s.source_id"  # noqa: S608
        f" WHERE s.id IN ({marks})",
        ids,
    ).fetchall()
    return {int(item["id"]): item for item in _serialize(conn, rows, preview=True)}


# ── 목록 쿼리 매개변수 ────────────────────────────────


def _parse_id_filter(raw: str, what: str) -> int | None:
    """숫자 형식이 아니면 400. 범위 밖(없는 id)이면 None → 결과가 빈다."""
    value = raw.strip()
    if not _INT_TEXT.match(value):
        raise invalid_input(f"{what} 형식이 올바르지 않습니다.")
    number = int(value)
    return number if id_in_range(number) else None


def _parse_limit(raw: str | None) -> int:
    if raw is None:
        return LIMIT_DEFAULT
    value = raw.strip()
    if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= LIMIT_MAX:
        raise invalid_input(f"limit은 1~{LIMIT_MAX} 사이 숫자여야 합니다.")
    return int(value)


def _choice(raw: str | None, allowed: tuple[str, ...], what: str) -> str | None:
    if raw is None:
        return None
    if raw not in allowed:
        raise invalid_input(f"{what} 값이 올바르지 않습니다.")
    return raw


def _b64(data: object) -> str:
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _bad_cursor() -> Exception:
    return invalid_input("cursor가 올바르지 않습니다. 목록을 처음부터 다시 불러와 주세요.")


def _encode_cursor(sort: str, row: sqlite3.Row) -> str:
    if sort == "due":
        return _b64(["due", row["due_date"], row["created_at"], row["id"]])
    return _b64(["created", row["created_at"], row["id"]])


def _decode_cursor(raw: str, sort: str) -> list[object]:
    """형식이 틀리거나 다른 `sort`로 만든 cursor는 400."""
    if len(raw) > 512:
        raise _bad_cursor()
    try:
        padded = raw + "=" * (-len(raw) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeError, binascii.Error):
        raise _bad_cursor() from None
    if not isinstance(data, list) or not data or data[0] != sort:
        raise _bad_cursor()
    if sort == "created":
        ok = len(data) == 3 and isinstance(data[1], str) and _is_id(data[2])
    else:
        ok = (
            len(data) == 4
            and (data[1] is None or isinstance(data[1], str))
            and isinstance(data[2], str)
            and _is_id(data[3])
        )
    if not ok:
        raise _bad_cursor()
    return data[1:]


def _is_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and id_in_range(value)


# ── 라우트 ──────────────────────────────────────────


@router.get("")
def list_scraps(
    request: Request,
    conn: DbConn,
    q: str | None = None,
    source_id: str | None = None,
    topic_ids: str | None = None,
    liked: str | None = None,
    due: str | None = None,
    sort: str | None = None,
    cursor: str | None = None,
    limit: str | None = None,
) -> dict[str, object]:
    sort_by = _choice(sort, ("created", "due"), "sort") or "created"
    page_size = _parse_limit(limit)
    liked_filter = _choice(liked, ("true", "false"), "liked")
    due_filter = _choice(due, ("upcoming", "past"), "due")
    words = parse_query(q)

    where: list[str] = []
    params: list[object] = []
    empty = False  # 없는 id 필터: 오류 없이 빈 결과

    if source_id is not None:
        sid = _parse_id_filter(source_id, "source_id")
        if sid is None:
            empty = True
        else:
            where.append("s.source_id = ?")
            params.append(sid)

    if topic_ids is not None and topic_ids.strip():
        parts = topic_ids.split(",")
        if len(parts) > _FILTER_IDS_MAX:
            raise invalid_input(f"topic_ids는 최대 {_FILTER_IDS_MAX}개까지 넣을 수 있습니다.")
        for tid in dict.fromkeys(_parse_id_filter(p, "topic_ids") for p in parts):
            if tid is None:
                empty = True
                continue
            where.append(
                "EXISTS (SELECT 1 FROM scrap_topics st WHERE st.scrap_id = s.id"
                " AND st.topic_id = ?)"
            )
            params.append(tid)

    if liked_filter is not None:
        where.append("s.liked = ?")
        params.append(1 if liked_filter == "true" else 0)

    if due_filter is not None:
        clock: Clock = request.app.state.clock
        today = datetime.fromtimestamp(clock.now(), KST).date()
        if due_filter == "upcoming":
            where.append("s.due_date IS NOT NULL AND s.due_date BETWEEN ? AND ?")
            params.extend(
                [today.isoformat(), (today + timedelta(days=DUE_UPCOMING_DAYS)).isoformat()]
            )
        else:
            where.append("s.due_date IS NOT NULL AND s.due_date < ?")
            params.append(today.isoformat())

    clauses, search_params = search_conditions(words)
    where.extend(clauses)
    params.extend(search_params)

    if cursor is not None:
        values = _decode_cursor(cursor, sort_by)
        if sort_by == "created":
            created, last_id = values
            where.append("(s.created_at < ? OR (s.created_at = ? AND s.id < ?))")
            params.extend([created, created, last_id])
        else:
            due_value, created, last_id = values
            after_same_due = "(s.created_at < ? OR (s.created_at = ? AND s.id < ?))"
            if due_value is None:
                where.append(f"(s.due_date IS NULL AND {after_same_due})")
                params.extend([created, created, last_id])
            else:
                where.append(
                    "(s.due_date IS NULL OR s.due_date > ?"
                    f" OR (s.due_date = ? AND {after_same_due}))"
                )
                params.extend([due_value, due_value, created, created, last_id])

    if empty:
        return {"items": [], "next_cursor": None}

    order = (
        "s.due_date IS NULL, s.due_date, s.created_at DESC, s.id DESC"
        if sort_by == "due"
        else "s.created_at DESC, s.id DESC"
    )
    # 조건 문자열은 모두 이 모듈·app/search.py 의 고정 SQL 조각이고, 값은 매개변수로만 넘긴다.
    sql = (
        f"SELECT {_LIST_COLUMNS} FROM scraps s JOIN sources src ON src.id = s.source_id"  # noqa: S608
        + (" WHERE " + " AND ".join(where) if where else "")
        + f" ORDER BY {order} LIMIT ?"
    )
    try:
        rows = conn.execute(sql, [*params, page_size + 1]).fetchall()
    except sqlite3.OperationalError:
        if not words:
            raise
        # 검색식은 모두 인용하므로 생기지 않아야 하지만, 생겨도 500 대신 입력 오류로 답한다.
        logger.warning("검색 쿼리 실패 (검색어는 기록하지 않음)")
        raise invalid_input("검색어를 처리할 수 없습니다. 다른 검색어로 시도해 주세요.") from None
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    return {
        "items": _serialize(conn, rows, preview=True),
        "next_cursor": _encode_cursor(sort_by, rows[-1]) if has_more else None,
    }


@router.post("", status_code=201)
def create_scrap(body: ScrapCreate, request: Request, conn: DbConn) -> dict[str, object]:
    url = validate_url(body.url)
    title = _clean_title(body.title, url)
    memo = _check_memo(body.memo)
    due_date = validate_due_date(body.due_date)
    now = _now_iso(request)
    with transaction(conn):
        if body.source_id is None:
            source_id = detect_source_id(conn, url)
        else:
            source_id = _check_source(conn, body.source_id)
        topic_ids = _clean_topic_ids(conn, body.topic_ids)
        cur = conn.execute(
            "INSERT INTO scraps (url, title, memo, source_id, liked, due_date,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (url, title, memo, source_id, int(body.liked), due_date, now, now),
        )
        scrap_id = int(cur.lastrowid or 0)
        _set_topics(conn, scrap_id, topic_ids)
    return _load_scrap(conn, scrap_id)


@router.get("/{scrap_id}")
def get_scrap(scrap_id: int, conn: DbConn) -> dict[str, object]:
    if not id_in_range(scrap_id):
        raise _scrap_not_found()
    return _load_scrap(conn, scrap_id)


@router.patch("/{scrap_id}")
def update_scrap(
    scrap_id: int, body: ScrapUpdate, request: Request, conn: DbConn
) -> dict[str, object]:
    if not id_in_range(scrap_id):
        raise _scrap_not_found()
    fields = body.model_fields_set
    for name in ("url", "memo", "source_id", "topic_ids"):
        if name in fields and getattr(body, name) is None:
            raise invalid_input(f"{name}에는 null을 넣을 수 없습니다.")

    with transaction(conn):
        row = conn.execute(
            "SELECT url, title, memo, source_id, due_date FROM scraps WHERE id = ?", (scrap_id,)
        ).fetchone()
        if row is None:
            raise _scrap_not_found()
        new = {k: row[k] for k in ("url", "title", "memo", "source_id", "due_date")}
        if body.url is not None:
            new["url"] = validate_url(body.url)
        if "title" in fields:
            new["title"] = _clean_title(body.title, str(new["url"]))
        if body.memo is not None:
            new["memo"] = _check_memo(body.memo)
        if body.source_id is not None:
            new["source_id"] = _check_source(conn, body.source_id)
        if "due_date" in fields:
            new["due_date"] = validate_due_date(body.due_date)

        changed = any(new[k] != row[k] for k in new)
        if body.topic_ids is not None:
            topic_ids = _clean_topic_ids(conn, body.topic_ids)
            current = {
                int(r[0])
                for r in conn.execute(
                    "SELECT topic_id FROM scrap_topics WHERE scrap_id = ?", (scrap_id,)
                )
            }
            if set(topic_ids) != current:
                _set_topics(conn, scrap_id, topic_ids)
                changed = True

        if changed:
            conn.execute(
                "UPDATE scraps SET url = ?, title = ?, memo = ?, source_id = ?, due_date = ?,"
                " updated_at = ? WHERE id = ?",
                (
                    new["url"],
                    new["title"],
                    new["memo"],
                    new["source_id"],
                    new["due_date"],
                    _now_iso(request),
                    scrap_id,
                ),
            )
    return _load_scrap(conn, scrap_id)


@router.delete("/{scrap_id}", status_code=204)
def delete_scrap(scrap_id: int, conn: DbConn) -> Response:
    if not id_in_range(scrap_id):
        raise _scrap_not_found()
    cur = conn.execute("DELETE FROM scraps WHERE id = ?", (scrap_id,))
    if cur.rowcount == 0:
        raise _scrap_not_found()
    return Response(status_code=204)


@router.put("/{scrap_id}/like")
def set_like(scrap_id: int, body: LikeBody, conn: DbConn) -> dict[str, bool]:
    # 값 지정 방식(반복해도 결과 동일). updated_at은 바꾸지 않는다.
    if not id_in_range(scrap_id):
        raise _scrap_not_found()
    cur = conn.execute("UPDATE scraps SET liked = ? WHERE id = ?", (int(body.liked), scrap_id))
    if cur.rowcount == 0:
        raise _scrap_not_found()
    return {"liked": body.liked}
