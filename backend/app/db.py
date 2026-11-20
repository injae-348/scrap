"""SQLite 연결, 마이그레이션, 요청별 연결 의존성.

연결 방식: **요청마다 새 연결을 열고 요청이 끝나면 닫는다.**
- uvicorn 워커 1개 안에서 동기 라우트는 스레드풀(여러 스레드)에서 동시에 돈다.
  연결 하나를 공유하면 전역 잠금으로 모든 요청을 직렬화하거나 트랜잭션이 섞일 위험이 있다.
- SQLite 연결 생성은 파일 열기 + PRAGMA 몇 개라 가볍다(수십 µs). 연결 풀이 필요 없는 규모다.
- 쓰기 경합은 SQLite 파일 잠금 + busy_timeout 으로 처리한다 (WAL이라 읽기는 쓰기와 동시에 가능).
- FastAPI는 동기 yield 의존성의 진입·종료와 라우트 본문을 서로 다른 스레드에서 실행할 수 있다.
  한 요청 안에서는 연결을 순서대로만 쓰므로 `check_same_thread=False`로 연다 (동시 사용은 없다).

트랜잭션: `isolation_level=None`(자동 커밋)으로 열고, 여러 문장을 묶을 때만 `transaction()`으로
`BEGIN IMMEDIATE ... COMMIT`을 명시한다.
"""

import logging
import os
import re
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import Request

from app.clock import to_iso
from app.errors import ApiError

logger = logging.getLogger("app")

CONNECT_TIMEOUT_SECONDS = 2.0
BUSY_TIMEOUT_MS = 5000
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_FILE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class DatabaseUnavailableError(Exception):
    """DB를 열 수 없거나 쓸 수 없는 상태. 메시지는 서버 로그용이며 응답에 넣지 않는다."""


def check_database(db_path: str) -> None:
    """DB 파일을 열어 `SELECT 1`을 실행하고, 읽기·쓰기 권한까지 확인한다.

    - 상위 디렉터리가 없으면 만들지 않고 실패한다 (운영에서 경로 실수를 숨기지 않기 위해).
    - 디렉터리는 있고 파일만 없으면 SQLite가 빈 DB 파일을 만든다 (첫 배포).
    - 파일이나 디렉터리에 쓰기 권한이 없으면 실패한다. 읽기 전용으로 열려
      `SELECT 1`만 통과하는 권한 불일치(예: 컨테이너 UID와 data/ 소유자 불일치)를 잡기 위함.
      디렉터리 쓰기 권한은 WAL 모드의 -wal/-shm 파일 생성에 필요하다.
    """
    path = Path(db_path)
    parent = path.parent

    if not parent.is_dir():
        raise DatabaseUnavailableError(f"DB 디렉터리가 없습니다: {parent}")

    try:
        # URI 없이 열면 SQLite 기본값(읽기·쓰기 + 없으면 생성)으로 열린다.
        conn = sqlite3.connect(path, timeout=CONNECT_TIMEOUT_SECONDS)
    except sqlite3.Error as exc:
        raise DatabaseUnavailableError(f"DB를 열 수 없습니다: {db_path}: {exc}") from exc

    try:
        row = conn.execute("SELECT 1").fetchone()
    except sqlite3.Error as exc:
        raise DatabaseUnavailableError(f"DB 쿼리 실패: {db_path}: {exc}") from exc
    finally:
        conn.close()

    if row != (1,):
        raise DatabaseUnavailableError(f"DB 쿼리 결과가 예상과 다릅니다: {row!r}")

    if not os.access(path, os.R_OK | os.W_OK):
        raise DatabaseUnavailableError(f"DB 파일에 읽기·쓰기 권한이 없습니다: {db_path}")
    if not os.access(parent, os.W_OK | os.X_OK):
        raise DatabaseUnavailableError(f"DB 디렉터리에 쓰기 권한이 없습니다: {parent}")


def _open(db_path: str) -> sqlite3.Connection:
    if not Path(db_path).parent.is_dir():
        # SQLite가 디렉터리를 만들지는 않지만, 원인이 분명한 오류로 바꿔 둔다.
        raise DatabaseUnavailableError(f"DB 디렉터리가 없습니다: {Path(db_path).parent}")
    try:
        conn = sqlite3.connect(
            db_path,
            timeout=BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        # WAL에서는 NORMAL로도 손상 없이 안전하다 (전원 차단 시 마지막 커밋 일부만 잃을 수 있음).
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.Error as exc:
        raise DatabaseUnavailableError(f"DB를 열 수 없습니다: {db_path}: {exc}") from exc
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """`BEGIN IMMEDIATE`로 쓰기 잠금을 먼저 잡고, 성공하면 커밋·예외면 롤백한다."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def list_migrations(directory: Path = MIGRATIONS_DIR) -> list[tuple[int, str, Path]]:
    found: list[tuple[int, str, Path]] = []
    for path in sorted(directory.iterdir()):
        match = _MIGRATION_FILE.match(path.name)
        if match:
            found.append((int(match.group(1)), path.name, path))
    versions = [v for v, _, _ in found]
    if len(versions) != len(set(versions)):
        raise RuntimeError("마이그레이션 번호가 중복됩니다.")
    return found


def apply_migrations(conn: sqlite3.Connection, now: float, directory: Path = MIGRATIONS_DIR) -> int:
    """아직 적용하지 않은 마이그레이션을 번호 순서대로 하나씩(각각 한 트랜잭션) 적용한다.

    - 적용 기록은 `schema_migrations`에 남긴다.
    - DB에 기록된 번호 중 이 코드가 모르는 것(새 버전에서 롤백한 경우)은 무시한다.
      그래서 마이그레이션은 이전 버전 코드와 호환되게(추가 위주로) 작성한다.
    반환값: 이번에 적용한 개수.
    """
    # WAL 모드는 DB 파일에 기록되어 이후 연결에도 유지된다.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY,"
        " name TEXT NOT NULL,"
        " applied_at TEXT NOT NULL)"
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    count = 0
    for version, name, path in list_migrations(directory):
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        # executescript 는 문장을 그대로 실행하므로, 기록 INSERT까지 한 트랜잭션으로 감싼다.
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{sql}\n;\n"
            "INSERT INTO schema_migrations (version, name, applied_at) "
            f"VALUES ({version}, '{name}', '{to_iso(now)}');\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        logger.info("마이그레이션 적용: %s", name)
        count += 1
    return count


class Database:
    """DB 경로와 마이그레이션 상태를 들고 있는 앱 단위 객체 (`app.state.db`)."""

    def __init__(self, db_path: str, clock_now: Callable[[], float]) -> None:
        self.db_path = db_path
        self._clock_now = clock_now
        self._migrated = False
        self._lock = threading.Lock()

    def ensure_migrated(self) -> None:
        """처음 한 번만 마이그레이션을 적용한다 (앱 시작 시 + 첫 연결 시 지연 적용).

        시작 시점에 DB 디렉터리가 없어 실패했더라도, 나중에 디렉터리가 생기면
        다음 연결에서 적용된다.
        """
        if self._migrated:
            return
        with self._lock:
            if self._migrated:
                return
            conn = _open(self.db_path)
            try:
                apply_migrations(conn, self._clock_now())
            except sqlite3.Error as exc:
                raise DatabaseUnavailableError(f"마이그레이션 실패: {exc}") from exc
            finally:
                conn.close()
            self._migrated = True

    def connect(self) -> sqlite3.Connection:
        self.ensure_migrated()
        return _open(self.db_path)


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """요청별 DB 연결 의존성. 같은 요청 안의 다른 의존성과 연결을 공유한다(FastAPI 캐시)."""
    database: Database = request.app.state.db
    try:
        conn = database.connect()
    except DatabaseUnavailableError as exc:
        logger.error("DB 연결 실패: %s", exc)
        raise ApiError(503, "db_unavailable", "데이터베이스에 연결할 수 없습니다.") from exc
    try:
        yield conn
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
