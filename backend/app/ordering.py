"""출처·주제의 사용자 지정 순서 (`PUT /sources/order`, `PUT /topics/order`)."""

import sqlite3
from typing import Literal

from pydantic import Field

from app.db import transaction
from app.validation import Id, StrictBody, invalid_input

OrderedTable = Literal["sources", "topics"]


class OrderBody(StrictBody):
    ids: list[Id] = Field(max_length=10_000)


def next_sort_order(conn: sqlite3.Connection, table: OrderedTable) -> int:
    """맨 뒤 순서 값. 호출하는 쪽의 트랜잭션 안에서 쓴다."""
    row = conn.execute(f"SELECT coalesce(max(sort_order), 0) + 1 FROM {table}").fetchone()  # noqa: S608
    return int(row[0])


def apply_order(conn: sqlite3.Connection, table: OrderedTable, ids: list[int]) -> None:
    """`ids`는 현재 있는 id 전부를 한 번씩 담아야 한다. 아니면 400."""
    with transaction(conn):
        existing = {int(r[0]) for r in conn.execute(f"SELECT id FROM {table}")}  # noqa: S608
        if len(ids) != len(set(ids)) or set(ids) != existing:
            raise invalid_input("순서 목록에는 현재 있는 항목을 빠짐없이 한 번씩 넣어야 합니다.")
        conn.executemany(
            f"UPDATE {table} SET sort_order = ? WHERE id = ?",  # noqa: S608
            [(position, item_id) for position, item_id in enumerate(ids, start=1)],
        )
