import sqlite3
from pathlib import Path

import pytest

from app.db import apply_migrations, list_migrations


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_apply_migrations_creates_auth_tables(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "m.db", isolation_level=None)
    try:
        assert apply_migrations(conn, now=1_800_000_000) == len(list_migrations())
        assert {
            "users",
            "recovery_codes",
            "sessions",
            "login_code_failures",
            "login_code_locks",
            "schema_migrations",
        } <= _tables(conn)
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations")]
        assert versions == [v for v, _, _ in list_migrations()]
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

        # 두 번째 실행은 아무것도 하지 않는다.
        assert apply_migrations(conn, now=1_800_000_000) == 0
    finally:
        conn.close()


def test_failed_migration_rolls_back(tmp_path: Path) -> None:
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "0001_ok.sql").write_text("CREATE TABLE a (id INTEGER);")
    (mig / "0002_bad.sql").write_text("CREATE TABLE b (id INTEGER); THIS IS NOT SQL;")
    conn = sqlite3.connect(tmp_path / "m.db", isolation_level=None)
    try:
        with pytest.raises(sqlite3.Error):
            apply_migrations(conn, now=0, directory=mig)
        tables = _tables(conn)
        assert "a" in tables
        assert "b" not in tables  # 실패한 마이그레이션은 통째로 롤백
        assert [r[0] for r in conn.execute("SELECT version FROM schema_migrations")] == [1]
    finally:
        conn.close()


def test_unknown_applied_versions_are_ignored(tmp_path: Path) -> None:
    # 새 버전에서 롤백한 경우: DB에는 이 코드가 모르는 번호가 기록되어 있다.
    conn = sqlite3.connect(tmp_path / "m.db", isolation_level=None)
    try:
        apply_migrations(conn, now=0)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at)"
            " VALUES (9999, '9999_future.sql', 'x')"
        )
        assert apply_migrations(conn, now=0) == 0
    finally:
        conn.close()


def test_app_applies_migrations_and_enables_foreign_keys(client) -> None:
    assert client.get("/api/health").status_code == 200
    conn = client.app.state.db.connect()
    try:
        assert {"users", "recovery_codes", "sessions"} <= _tables(conn)
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO sessions (user_id, token_hash, created_at, last_seen_at)"
                " VALUES (999, 'h', 'x', 'x')"
            )
    finally:
        conn.close()


def test_auth_endpoint_503_when_db_dir_missing(make_client, tmp_path: Path) -> None:
    client = make_client(DB_PATH=str(tmp_path / "missing" / "test.db"))
    res = client.get("/api/auth/status")
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "db_unavailable"
    assert not (tmp_path / "missing").exists()
