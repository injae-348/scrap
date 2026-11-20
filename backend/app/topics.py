"""주제 API `/api/topics` (docs/API.md v1.3 "출처·주제 관리").

주제 이름 변경·삭제 시 검색 색인(scraps_fts.topics)은 DB 트리거가 맞춘다 (0003_scraps.sql).
스크랩의 `updated_at`은 바꾸지 않는다. 이 라우터는 세션 필수 상위 라우터 아래에 붙는다.
"""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import Field

from app.db import get_db, transaction
from app.errors import ApiError
from app.ordering import OrderBody, apply_order, next_sort_order
from app.validation import StrictBody, clean_name, id_in_range, not_found

router = APIRouter(prefix="/topics")

DbConn = Annotated[sqlite3.Connection, Depends(get_db)]


class TopicBody(StrictBody):
    name: str = Field(max_length=1000)


def _topic_not_found() -> ApiError:
    return not_found("주제를 찾을 수 없습니다.")


def _check_name_free(conn: sqlite3.Connection, key: str, own_id: int | None) -> None:
    row = conn.execute("SELECT id FROM topics WHERE name_key = ?", (key,)).fetchone()
    if row is not None and row["id"] != own_id:
        raise ApiError(400, "duplicate_name", "같은 이름의 주제가 이미 있습니다.")


def _load_topic(conn: sqlite3.Connection, topic_id: int) -> dict[str, object]:
    row = conn.execute("SELECT id, name FROM topics WHERE id = ?", (topic_id,)).fetchone()
    if row is None:
        raise _topic_not_found()
    return {"id": row["id"], "name": row["name"]}


@router.get("")
def list_topics(conn: DbConn) -> list[dict[str, object]]:
    rows = conn.execute("SELECT id, name FROM topics ORDER BY sort_order, id").fetchall()
    return [{"id": row["id"], "name": row["name"]} for row in rows]


@router.post("", status_code=201)
def create_topic(body: TopicBody, conn: DbConn) -> dict[str, object]:
    name, key = clean_name(body.name, "주제")
    with transaction(conn):
        _check_name_free(conn, key, None)
        cur = conn.execute(
            "INSERT INTO topics (name, name_key, sort_order) VALUES (?, ?, ?)",
            (name, key, next_sort_order(conn, "topics")),
        )
    return _load_topic(conn, int(cur.lastrowid or 0))


@router.put("/order", status_code=204)
def order_topics(body: OrderBody, conn: DbConn) -> Response:
    apply_order(conn, "topics", body.ids)
    return Response(status_code=204)


@router.patch("/{topic_id}")
def update_topic(topic_id: int, body: TopicBody, conn: DbConn) -> dict[str, object]:
    if not id_in_range(topic_id):
        raise _topic_not_found()
    name, key = clean_name(body.name, "주제")
    with transaction(conn):
        if conn.execute("SELECT 1 FROM topics WHERE id = ?", (topic_id,)).fetchone() is None:
            raise _topic_not_found()
        _check_name_free(conn, key, topic_id)
        conn.execute("UPDATE topics SET name = ?, name_key = ? WHERE id = ?", (name, key, topic_id))
    return _load_topic(conn, topic_id)


@router.delete("/{topic_id}", status_code=204)
def delete_topic(topic_id: int, conn: DbConn) -> Response:
    if not id_in_range(topic_id):
        raise _topic_not_found()
    # scrap_topics 는 ON DELETE CASCADE 로 함께 지워진다.
    cur = conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
    if cur.rowcount == 0:
        raise _topic_not_found()
    return Response(status_code=204)
