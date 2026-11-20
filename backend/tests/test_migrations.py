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


def _schema(conn: sqlite3.Connection, names: set[str]) -> dict[str, str]:
    return {
        r[0]: r[1]
        for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL")
        if r[0] in names or any(r[0].startswith(n) for n in names)
    }


def test_scrap_migration_is_additive(tmp_path: Path) -> None:
    """0003 은 새 테이블만 추가한다: 기존 테이블 정의·데이터가 그대로다 (구 이미지 롤백 대비)."""
    older = tmp_path / "older"
    older.mkdir()
    for _, name, path in list_migrations():
        if name < "0003":
            (older / name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    conn = sqlite3.connect(tmp_path / "m.db", isolation_level=None)
    try:
        apply_migrations(conn, now=0, directory=older)
        conn.execute(
            "INSERT INTO users (username, password_hash, totp_secret, created_at)"
            " VALUES ('u', 'h', 's', 't')"
        )
        old_tables = _tables(conn) - {"schema_migrations"}
        before = _schema(conn, old_tables)

        assert apply_migrations(conn, now=0) >= 1
        assert _schema(conn, old_tables) == before
        assert conn.execute("SELECT username FROM users").fetchall() == [("u",)]
        assert {"sources", "source_patterns", "topics", "scraps", "scrap_topics", "scraps_fts"} <= (
            _tables(conn)
        )
    finally:
        conn.close()


def test_default_sources_seed(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "m.db", isolation_level=None)
    try:
        apply_migrations(conn, now=0)
        rows = conn.execute(
            "SELECT s.name, s.is_default, group_concat(p.pattern, ',')"
            " FROM sources s LEFT JOIN source_patterns p ON p.source_id = s.id"
            " GROUP BY s.id ORDER BY s.sort_order"
        ).fetchall()
        assert [(n, d, set((p or "").split(",")) - {""}) for n, d, p in rows] == [
            ("유튜브", 0, {"youtube.com", "youtu.be"}),
            ("X", 0, {"x.com", "twitter.com"}),
            ("일반사이트", 1, set()),
            ("당근", 0, {"daangn.com"}),
            ("커뮤니티", 0, set()),
        ]
        assert conn.execute("SELECT count(*) FROM topics").fetchone() == (0,)
        # 기본 출처는 하나만
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO sources (name, name_key, is_default, sort_order)"
                " VALUES ('또', '또', 1, 9)"
            )
    finally:
        conn.close()


def test_rollback_to_code_without_0003(make_client, clock, tmp_path: Path, monkeypatch) -> None:
    """0003까지 적용된 DB를 0001·0002만 아는 코드 경로로 열어도 기동·가입·로그인이 된다."""
    from functools import partial

    import app.db as db_module
    from tests.conftest import do_login, do_setup

    db_path = str(tmp_path / "rollback.db")
    new = make_client(clock=clock, DB_PATH=db_path)
    assert new.get("/api/health").status_code == 200  # 새 코드: 0001~0003 적용

    older = tmp_path / "older"
    older.mkdir()
    for _, name, path in list_migrations():
        if name < "0003":
            (older / name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(db_module, "apply_migrations", partial(apply_migrations, directory=older))

    old = make_client(clock=clock, DB_PATH=db_path)
    assert old.get("/api/health").status_code == 200
    assert old.get("/api/auth/status").json() == {"setup_required": True, "logged_in": False}
    secret, _ = do_setup(old, clock)
    old.post("/api/auth/logout")
    do_login(old, clock, secret)
    assert old.get("/api/auth/sessions").status_code == 200

    conn = sqlite3.connect(db_path)
    try:
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations")]
    finally:
        conn.close()
    assert versions == [1, 2, 3]  # 구 코드는 3번을 다시 적용하거나 지우지 않는다
