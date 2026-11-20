import os
import stat
from pathlib import Path

import pytest

DB_ERROR = {"error": {"code": "db_unavailable", "message": "데이터베이스에 연결할 수 없습니다."}}

needs_non_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root는 파일 권한을 무시하므로 권한 테스트가 의미 없다",
)


def test_health_ok_with_db(make_client, tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    client = make_client(DB_PATH=str(db_path))

    res = client.get("/api/health")

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    # 디렉터리가 있으면 빈 DB 파일이 생긴다 (첫 배포).
    assert db_path.is_file()


def test_health_ok_with_existing_db(make_client, tmp_path: Path) -> None:
    db_path = tmp_path / "existing.db"
    client = make_client(DB_PATH=str(db_path))
    assert client.get("/api/health").status_code == 200

    # 두 번째 요청도 같은 파일을 열어 성공한다 (요청마다 열고 닫음).
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_health_does_not_require_anthropic_key(make_client, tmp_path: Path) -> None:
    # ANTHROPIC_API_KEY 없이도 앱이 뜬다 (SESSION_SECRET은 필수 — test_config.py).
    assert "ANTHROPIC_API_KEY" not in os.environ
    client = make_client(DB_PATH=str(tmp_path / "test.db"))
    assert client.get("/api/health").status_code == 200


def test_health_503_when_parent_dir_missing(make_client, tmp_path: Path) -> None:
    missing_dir = tmp_path / "missing"
    client = make_client(DB_PATH=str(missing_dir / "test.db"))

    res = client.get("/api/health")

    assert res.status_code == 503
    assert res.json() == DB_ERROR
    # 상위 디렉터리를 만들지 않는다 (운영 경로 실수를 숨기지 않기 위해).
    assert not missing_dir.exists()


def test_health_503_when_path_is_directory(make_client, tmp_path: Path) -> None:
    client = make_client(DB_PATH=str(tmp_path))

    res = client.get("/api/health")

    assert res.status_code == 503
    assert res.json() == DB_ERROR


@needs_non_root
def test_health_503_when_dir_not_accessible(make_client, tmp_path: Path) -> None:
    # 운영 data/ 소유자(UID)가 컨테이너 UID와 다른 경우(700)를 흉내 낸다.
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_dir.chmod(0)
    try:
        client = make_client(DB_PATH=str(data_dir / "scrap.db"))
        res = client.get("/api/health")
    finally:
        data_dir.chmod(stat.S_IRWXU)

    assert res.status_code == 503
    assert res.json() == DB_ERROR


@needs_non_root
def test_health_503_when_db_file_read_only(make_client, tmp_path: Path) -> None:
    # 파일은 읽히지만 쓸 수 없으면 SELECT 1은 통과한다. 이것도 실패로 잡아야 한다.
    db_path = tmp_path / "scrap.db"
    client = make_client(DB_PATH=str(db_path))
    assert client.get("/api/health").status_code == 200

    db_path.chmod(stat.S_IRUSR)
    try:
        res = client.get("/api/health")
    finally:
        db_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    assert res.status_code == 503
    assert res.json() == DB_ERROR


@needs_non_root
def test_health_503_when_dir_read_only(make_client, tmp_path: Path) -> None:
    # 디렉터리에 쓸 수 없으면 WAL 파일(-wal, -shm)을 만들 수 없다.
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "scrap.db"
    client = make_client(DB_PATH=str(db_path))
    assert client.get("/api/health").status_code == 200

    data_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        res = client.get("/api/health")
    finally:
        data_dir.chmod(stat.S_IRWXU)

    assert res.status_code == 503
    assert res.json() == DB_ERROR


def test_health_503_does_not_leak_path(make_client, tmp_path: Path) -> None:
    secret_dir = tmp_path / "some-internal-dir"
    client = make_client(DB_PATH=str(secret_dir / "test.db"))

    res = client.get("/api/health")

    assert res.status_code == 503
    assert "some-internal-dir" not in res.text


def test_health_method_not_allowed(make_client, tmp_path: Path) -> None:
    client = make_client(DB_PATH=str(tmp_path / "test.db"))

    res = client.post("/api/health")

    assert res.status_code == 405
    assert res.json()["error"]["code"] == "method_not_allowed"
