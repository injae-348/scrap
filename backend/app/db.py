"""SQLite 연결 확인.

Phase 3에서는 요청마다 연결을 열고 닫는 단순한 방식만 쓴다.
DB 생성·마이그레이션은 아직 하지 않는다 (Phase 4~).
"""

import os
import sqlite3
from pathlib import Path

CONNECT_TIMEOUT_SECONDS = 2.0


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
