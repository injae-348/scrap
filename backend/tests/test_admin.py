"""운영 관리 명령 `python -m app.admin` (가짜 터미널·가짜 시계, 임시 DB)."""

import io
import logging
import re
import sqlite3
from collections.abc import Callable

import pyotp
import pytest
from fastapi.testclient import TestClient

import app.admin as admin
from app.auth.crypto import recovery_code_hash
from tests.conftest import (
    FAKE_PASSWORD,
    FAKE_USERNAME,
    FakeClock,
    do_login,
    do_setup,
    totp_now,
)

# 테스트 전용 가짜 TOTP 비밀값·비밀번호 (실제 값 아님).
NEW_SECRET = "TESTONLYFAKESECRETAAAAAAAAAAAAAA"  # noqa: S105
NEW_PASSWORD = "test-only-new-password-0000"  # noqa: S105


class FakeConsole(admin.Console):
    def __init__(
        self, lines: list[object] | None = None, secrets: list[object] | None = None, tty=True
    ) -> None:
        super().__init__(
            out=io.StringIO(),
            err=io.StringIO(),
            read_line=self._next(lines or [], "line"),
            read_secret=self._next(secrets or [], "secret"),
            interactive=lambda: tty,
        )
        self.prompts: list[str] = []

    def _next(self, queue: list[object], kind: str) -> Callable[[str], str]:
        def read(prompt: str) -> str:
            self.prompts.append(prompt)
            if not queue:
                raise AssertionError(f"예상보다 많은 입력 요청 ({kind})")
            item = queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            return str(item)

        return read

    @property
    def text(self) -> str:
        return self.out.getvalue()

    @property
    def error(self) -> str:
        return self.err.getvalue()


def run(client: TestClient, clock: FakeClock, console: FakeConsole, *argv: str) -> int:
    return admin.main(list(argv), console=console, settings=client.app.state.settings, clock=clock)


def db(client: TestClient) -> sqlite3.Connection:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def auth_state(client: TestClient) -> tuple:
    conn = db(client)
    try:
        user = tuple(conn.execute("SELECT password_hash, totp_secret FROM users").fetchone())
        codes = sorted(r[0] for r in conn.execute("SELECT code_hash FROM recovery_codes"))
        sessions = conn.execute("SELECT count(*) FROM sessions").fetchone()[0]
    finally:
        conn.close()
    return user, codes, sessions


@pytest.fixture
def setup_done(client: TestClient, clock: FakeClock) -> tuple[str, list[str]]:
    secret, codes = do_setup(client, clock)
    assert auth_state(client)[2] == 1  # 가입한 기기의 세션
    return secret, codes


@pytest.fixture
def fixed_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(admin, "new_totp_secret", lambda: NEW_SECRET)
    return NEW_SECRET


# ── 공통 ────────────────────────────────────────────


def test_help_is_korean(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        admin.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "사용법:" in out and "reset-2fa" in out and "ai-usage" in out and "종료 코드" in out


def test_unknown_command_is_usage_error(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        admin.main(["nope"])
    assert exc.value.code == 2


def test_missing_db_is_not_created(client: TestClient, clock: FakeClock, tmp_path) -> None:
    from dataclasses import replace

    settings = replace(client.app.state.settings, db_path=str(tmp_path / "none.db"))
    console = FakeConsole()
    assert admin.main(["fts-check"], console=console, settings=settings, clock=clock) == 2
    assert "DB 파일이 없습니다" in console.error
    assert not (tmp_path / "none.db").exists()


@pytest.mark.parametrize("command", ["reset-2fa", "set-password"])
def test_no_user(client: TestClient, clock: FakeClock, command: str) -> None:
    assert client.get("/api/health").status_code == 200  # DB 생성
    console = FakeConsole()
    assert run(client, clock, console, command) == 1
    assert "가입한 사용자가 없습니다" in console.error


# ── reset-2fa ───────────────────────────────────────


def test_reset_2fa_refuses_without_terminal(client, clock, setup_done) -> None:
    before = auth_state(client)
    console = FakeConsole(tty=False)
    assert run(client, clock, console, "reset-2fa") == 2
    assert "터미널" in console.error
    assert console.prompts == [] and console.text == ""
    assert auth_state(client) == before


def test_reset_2fa_cancel_at_confirm(client, clock, setup_done) -> None:
    before = auth_state(client)
    console = FakeConsole(lines=["no"])
    assert run(client, clock, console, "reset-2fa") == 1
    assert auth_state(client) == before


def test_reset_2fa_wrong_codes_change_nothing(client, clock, setup_done, fixed_secret) -> None:
    before = auth_state(client)
    console = FakeConsole(lines=["yes", "000000", "abc", "12345678"])
    assert run(client, clock, console, "reset-2fa") == 1
    assert "아무것도 바꾸지 않았습니다" in console.error
    assert auth_state(client) == before


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), EOFError()])
def test_reset_2fa_interrupt_changes_nothing(
    client, clock, setup_done, fixed_secret, interrupt
) -> None:
    before = auth_state(client)
    console = FakeConsole(lines=["yes", interrupt])
    assert run(client, clock, console, "reset-2fa") == 130
    assert "아무것도 바꾸지 않았습니다" in console.error
    assert auth_state(client) == before


def test_reset_2fa_success(client, clock, setup_done, fixed_secret, caplog) -> None:
    old_secret, old_codes = setup_done
    old_user, _, _ = auth_state(client)
    caplog.set_level(logging.DEBUG)
    code = pyotp.TOTP(NEW_SECRET).at(clock.now())
    console = FakeConsole(lines=["YES", "111111", code])
    assert run(client, clock, console, "reset-2fa") == 0, console.error

    out = console.text
    # QR(ASCII)과 수동 입력 키, 새 복구 코드 10개를 화면에만 보여 준다
    assert "█" in out
    assert " ".join(re.findall(".{4}", NEW_SECRET)) in out
    new_codes = re.findall(r"\b[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}\b", out)
    assert len(set(new_codes)) == 10

    (password_hash, totp_secret), code_hashes, sessions = auth_state(client)
    assert password_hash == old_user[0]  # 비밀번호는 그대로
    assert totp_secret == NEW_SECRET
    assert sessions == 0  # 모든 세션 삭제
    assert code_hashes == sorted(recovery_code_hash(c) for c in new_codes)
    assert not set(code_hashes) & {recovery_code_hash(c) for c in old_codes}

    # 비밀값은 로그로 가지 않는다
    logged = "\n".join(r.getMessage() for r in caplog.records)
    for value in [NEW_SECRET, *new_codes]:
        assert value not in logged

    # 기존 세션은 401, 새 인증 앱으로 로그인된다. 옛 인증 앱 코드는 거부.
    assert client.get("/api/auth/sessions").status_code == 401
    res = client.post(
        "/api/auth/login", json={"username": FAKE_USERNAME, "password": FAKE_PASSWORD}
    )
    clock.advance(30)
    old = client.post(
        "/api/auth/login/verify",
        json={"challenge_id": res.json()["challenge_id"], "code": totp_now(old_secret, clock)},
    )
    assert old.status_code == 401
    do_login(client, clock, NEW_SECRET)
    assert client.get("/api/auth/sessions").status_code == 200


def test_reset_2fa_clears_account_lock(client, clock, setup_done, fixed_secret) -> None:
    conn = db(client)
    try:
        user_id = conn.execute("SELECT id FROM users").fetchone()[0]
        conn.execute(
            "INSERT INTO login_code_locks (user_id, locked_until) VALUES (?, ?)",
            (user_id, clock.now() + 3600),
        )
        conn.execute(
            "INSERT INTO login_code_failures (user_id, failed_at) VALUES (?, ?)",
            (user_id, clock.now()),
        )
        conn.commit()
    finally:
        conn.close()
    console = FakeConsole(lines=["yes", pyotp.TOTP(NEW_SECRET).at(clock.now())])
    assert run(client, clock, console, "reset-2fa") == 0
    conn = db(client)
    try:
        assert conn.execute("SELECT count(*) FROM login_code_locks").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM login_code_failures").fetchone()[0] == 0
    finally:
        conn.close()
    clock.advance(30)
    do_login(client, clock, NEW_SECRET)


# ── set-password ────────────────────────────────────


def test_set_password_refuses_without_terminal(client, clock, setup_done) -> None:
    before = auth_state(client)
    console = FakeConsole(tty=False)
    assert run(client, clock, console, "set-password") == 2
    assert console.prompts == []
    assert auth_state(client) == before


@pytest.mark.parametrize(
    "secrets",
    [
        ["short-pw"],  # 10자 미만
        ["x" * 1025],
        [NEW_PASSWORD, NEW_PASSWORD + "x"],  # 두 번이 다름
        [NEW_PASSWORD, KeyboardInterrupt()],
    ],
)
def test_set_password_failures_change_nothing(client, clock, setup_done, secrets) -> None:
    before = auth_state(client)
    console = FakeConsole(secrets=list(secrets))
    assert run(client, clock, console, "set-password") in (1, 130)
    assert auth_state(client) == before


def test_set_password_success(client, clock, setup_done, caplog) -> None:
    secret, _ = setup_done
    caplog.set_level(logging.DEBUG)
    console = FakeConsole(secrets=[NEW_PASSWORD, NEW_PASSWORD])
    assert run(client, clock, console, "set-password") == 0, console.error
    assert NEW_PASSWORD not in console.text
    assert NEW_PASSWORD not in "\n".join(r.getMessage() for r in caplog.records)
    assert auth_state(client)[2] == 0
    assert client.get("/api/auth/sessions").status_code == 401
    old = client.post(
        "/api/auth/login", json={"username": FAKE_USERNAME, "password": FAKE_PASSWORD}
    )
    assert old.status_code == 401
    res = client.post("/api/auth/login", json={"username": FAKE_USERNAME, "password": NEW_PASSWORD})
    assert res.status_code == 200
    verify = client.post(
        "/api/auth/login/verify",
        json={"challenge_id": res.json()["challenge_id"], "code": totp_now(secret, clock)},
    )
    assert verify.status_code == 204


# ── fts-check / fts-rebuild ─────────────────────────


@pytest.fixture
def with_scraps(user: TestClient) -> TestClient:
    tid = user.post("/api/topics", json={"name": "공모전"}).json()["id"]
    for i, title in enumerate(["대학생 공모전 안내", "해커톤 대회", "김치찌개 레시피"]):
        res = user.post(
            "/api/scraps",
            json={
                "url": f"https://ex.test/{i}",
                "title": title,
                "memo": "메모 내용",
                "topic_ids": [tid],
            },
        )
        assert res.status_code == 201, res.text
    return user


def search_ids(client: TestClient, q: str) -> list[int]:
    return [i["id"] for i in client.get("/api/scraps", params={"q": q}).json()["items"]]


def test_fts_check_ok(with_scraps, clock) -> None:
    console = FakeConsole(tty=False)  # 터미널이 아니어도 된다
    assert run(with_scraps, clock, console, "fts-check") == 0
    assert console.text.strip() == "✅ 검색 색인 정상: 스크랩 3개, 색인 3행"


@pytest.mark.parametrize(
    ("damage", "expected"),
    [
        ("DELETE FROM scraps_fts WHERE rowid = (SELECT min(id) FROM scraps)", "색인에 없음 1"),
        (
            "UPDATE scraps_fts SET title = '엉뚱한' WHERE rowid = (SELECT min(id) FROM scraps)",
            "내용 다름 1",
        ),
        (
            "UPDATE scraps_fts SET topics = '' WHERE rowid = (SELECT max(id) FROM scraps)",
            "내용 다름 1",
        ),
        ("INSERT INTO scraps_fts (rowid, title) VALUES (99999, '유령')", "색인에만 있음 1"),
    ],
)
def test_fts_check_detects_and_rebuild_fixes(with_scraps, clock, damage, expected) -> None:
    conn = db(with_scraps)
    try:
        conn.execute(damage)
        conn.commit()
    finally:
        conn.close()
    console = FakeConsole(tty=False)
    assert run(with_scraps, clock, console, "fts-check") == 1
    line = console.text.strip()
    assert line.startswith("❌ 검색 색인 이상") and expected in line and "fts-rebuild" in line

    console = FakeConsole(tty=False)
    assert run(with_scraps, clock, console, "fts-rebuild") == 0
    assert console.text.splitlines() == [
        "검색 색인을 다시 만들었습니다 (3행).",
        "✅ 검색 색인 정상: 스크랩 3개, 색인 3행",
    ]
    assert len(search_ids(with_scraps, "공모전")) == 3  # 주제 이름까지 다시 색인
    assert len(search_ids(with_scraps, "해커톤")) == 1
    # 트리거는 그대로 동작한다
    res = with_scraps.post(
        "/api/scraps", json={"url": "https://ex.test/new", "title": "새 글 제목"}
    )
    assert res.status_code == 201
    assert search_ids(with_scraps, "새 글 제목") == [res.json()["id"]]
    assert run(with_scraps, clock, FakeConsole(tty=False), "fts-check") == 0


def test_fts_corrupted_index_detected_and_rebuilt(with_scraps, clock) -> None:
    conn = db(with_scraps)
    try:
        # 색인 블록을 0으로 덮어써 실제로 손상시킨다 (구조 블록 id 1·10은 남긴다)
        conn.execute("UPDATE scraps_fts_data SET block = zeroblob(length(block)) WHERE id > 10")
        conn.commit()
    finally:
        conn.close()
    console = FakeConsole(tty=False)
    assert run(with_scraps, clock, console, "fts-check") == 1
    assert "FTS5 무결성 검사 실패" in console.text

    console = FakeConsole(tty=False)
    assert run(with_scraps, clock, console, "fts-rebuild") == 0, console.error
    assert console.text.splitlines()[-1] == "✅ 검색 색인 정상: 스크랩 3개, 색인 3행"
    assert len(search_ids(with_scraps, "공모전")) == 3


def test_fts_rebuild_on_empty_db(user, clock) -> None:
    console = FakeConsole(tty=False)
    assert run(user, clock, console, "fts-rebuild") == 0
    assert console.text.splitlines()[-1] == "✅ 검색 색인 정상: 스크랩 0개, 색인 0행"


# ── ai-usage ────────────────────────────────────────


def test_ai_usage_table(client, clock) -> None:
    assert client.get("/api/health").status_code == 200
    conn = db(client)
    try:
        conn.executemany(
            "INSERT INTO ai_usage_days (day, count, tokens) VALUES (?, ?, ?)",
            [("2027-01-15", 3, 12345), ("2027-01-13", 1, 999), ("2026-12-01", 50, 7)],
        )
        conn.commit()
    finally:
        conn.close()
    console = FakeConsole(tty=False)
    assert run(client, clock, console, "ai-usage") == 0
    lines = console.text.splitlines()
    assert lines[0] == "AI 사용량 (Asia/Seoul 날짜, 최근 14일)"
    rows = lines[2:-2]
    assert len(rows) == 14
    assert rows[0].split() == ["2027-01-15", "3", "12,345"]
    assert rows[1].split() == ["2027-01-14", "0", "0"]
    assert rows[2].split() == ["2027-01-13", "1", "999"]
    assert lines[-2].split() == ["합계", "4", "13,344"]  # 14일 밖(2026-12-01)은 빠진다
    assert "AI_PER_DAY" in lines[-1] and "AI_TOKENS_PER_DAY" in lines[-1]
    assert "sk-ant" not in console.text

    console = FakeConsole(tty=False)
    assert run(client, clock, console, "ai-usage", "--days", "60") == 0
    assert console.text.splitlines()[-2].split() == ["합계", "54", "13,351"]


@pytest.mark.parametrize("days", ["0", "-1", "abc", "4000"])
def test_ai_usage_days_validation(client, clock, days) -> None:
    with pytest.raises(SystemExit) as exc:
        run(client, clock, FakeConsole(tty=False), "ai-usage", "--days", days)
    assert exc.value.code == 2
