"""운영 관리 명령: `python -m app.admin <명령>` (작업 디렉터리 backend/, 컨테이너에서는 /app).

서버에서는 앱이 돌고 있는 api 컨테이너 안에서 실행한다 (SQLite WAL이라 앱과 동시에 써도 된다):

    docker compose exec api python -m app.admin fts-check

명령
- `reset-2fa`    인증 앱과 복구 코드를 모두 잃었을 때 2차 인증(TOTP)을 새로 등록한다. 터미널 필수.
- `set-password` 비밀번호를 바꾼다. 터미널 필수.
- `fts-check`    검색 색인(`scraps_fts`) 무결성 검사. 정상 0, 이상 1.
- `fts-rebuild`  검색 색인을 스크랩 테이블에서 다시 만든다(한 트랜잭션).
                 결과 판정은 fts-check와 같다.
- `ai-usage`     날짜별 AI 요청 수·토큰 수.

종료 코드: 0 성공·정상, 1 실패·이상·취소(아무것도 바꾸지 않음),
2 실행 환경 문제(터미널 아님, 설정·DB 오류, 사용법 오류), 130 Ctrl+C(아무것도 바꾸지 않음).

비밀번호·TOTP 비밀값·복구 코드는 화면(터미널)에만 출력하고 로그(logger)로 보내지 않는다.
비밀값을 다루는 명령은 표준입력·출력이 모두 터미널일 때만 실행한다 (파일·파이프·로그로 새지 않게).
"""

import argparse
import getpass
import sqlite3
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TextIO

import pyotp
import qrcode

from app.auth.crypto import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    TOTP_ISSUER,
    hash_password,
    match_totp,
    new_recovery_codes,
    new_totp_secret,
    recovery_code_hash,
)
from app.clock import KST, Clock
from app.config import ConfigError, Settings, load_settings
from app.db import Database, DatabaseUnavailableError, transaction

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_ENV = 2
EXIT_INTERRUPTED = 130

TOTP_ATTEMPTS = 3
AI_USAGE_DEFAULT_DAYS = 14
AI_USAGE_MAX_DAYS = 3660
PROG = "python -m app.admin"


@dataclass
class Console:
    """입출력 (테스트는 가짜를 넣는다)."""

    out: TextIO = field(default_factory=lambda: sys.stdout)
    err: TextIO = field(default_factory=lambda: sys.stderr)
    read_line: Callable[[str], str] = input
    read_secret: Callable[[str], str] = getpass.getpass
    interactive: Callable[[], bool] = field(
        default=lambda: sys.stdin.isatty() and sys.stdout.isatty()
    )

    def say(self, text: str = "") -> None:
        print(text, file=self.out, flush=True)

    def warn(self, text: str) -> None:
        print(text, file=self.err, flush=True)


class AdminError(Exception):
    """명령을 끝낸다. `code`는 종료 코드, 메시지는 표준오류로 (비밀값을 넣지 않는다)."""

    def __init__(self, message: str, code: int = EXIT_ENV) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Context:
    console: Console
    settings: Settings
    clock: Clock

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if not Path(self.settings.db_path).is_file():
            # 없는 경로에 빈 DB를 새로 만들지 않는다.
            raise AdminError("DB 파일이 없습니다. DB_PATH 를 확인하세요.")
        try:
            conn = Database(self.settings.db_path, self.clock.now).connect()
        except DatabaseUnavailableError:
            raise AdminError("DB를 열 수 없습니다 (경로·권한 확인).") from None
        try:
            yield conn
        finally:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            conn.close()


# ── 공통 ────────────────────────────────────────────


def _require_terminal(console: Console) -> None:
    if not console.interactive():
        raise AdminError(
            "이 명령은 터미널에서만 실행합니다 (표준입력·출력이 모두 터미널이어야 함). "
            "docker compose exec 에 -T 를 붙이지 말고, 출력을 파일·파이프로 돌리지 마세요."
        )


def _single_user(conn: sqlite3.Connection) -> sqlite3.Row:
    rows = conn.execute("SELECT id, username FROM users ORDER BY id LIMIT 2").fetchall()
    if not rows:
        raise AdminError(
            "가입한 사용자가 없습니다. 최초 가입은 웹 화면에서 진행합니다 (바꾼 것 없음).",
            EXIT_FAIL,
        )
    if len(rows) > 1:
        raise AdminError("사용자가 둘 이상입니다. 이 명령은 1인용 DB만 다룹니다 (바꾼 것 없음).")
    return rows[0]


def _confirm(console: Console, question: str) -> None:
    answer = console.read_line(f"{question} 계속하려면 yes 를 입력하세요: ").strip().lower()
    if answer != "yes":
        raise AdminError("취소했습니다. 아무것도 바꾸지 않았습니다.", EXIT_FAIL)


def _group(value: str, size: int = 4) -> str:
    return " ".join(value[i : i + size] for i in range(0, len(value), size))


# ── reset-2fa ───────────────────────────────────────


def _print_qr(console: Console, uri: str, light_background: bool) -> None:
    qr = qrcode.QRCode(border=2)
    qr.add_data(uri)
    qr.make(fit=True)
    # 어두운 배경 터미널에서는 색을 뒤집어야 인증 앱이 읽는다.
    qr.print_ascii(out=console.out, invert=not light_background)
    console.out.flush()


def cmd_reset_2fa(ctx: Context, args: argparse.Namespace) -> int:
    console = ctx.console
    _require_terminal(console)
    with ctx.connect() as conn:
        user = _single_user(conn)
        console.say(f"계정: {user['username']}")
        console.say("2차 인증을 새로 등록합니다.")
        console.say("끝나면 기존 인증 앱 항목과 복구 코드는 모두 못 쓰게 되고,")
        console.say("모든 기기가 로그아웃됩니다.")
        console.say("중간에 Ctrl+C 를 누르면 아무것도 바뀌지 않습니다.")
        _confirm(console, "2차 인증을 재설정할까요?")

        secret = new_totp_secret()
        uri = pyotp.TOTP(secret).provisioning_uri(name=user["username"], issuer_name=TOTP_ISSUER)
        console.say()
        console.say("인증 앱(Google Authenticator 등)으로 아래 QR을 찍으세요.")
        _print_qr(console, uri, args.light_background)
        console.say("QR이 읽히지 않으면 인증 앱의 '설정 키 입력'에 아래 키를 넣으세요 (시간 기준).")
        console.say(f"  계정 이름: {TOTP_ISSUER} ({user['username']})")
        console.say(f"  키: {_group(secret)}")
        console.say()

        step: int | None = None
        for attempt in range(1, TOTP_ATTEMPTS + 1):
            code = console.read_line(f"인증 앱에 보이는 6자리 코드 ({attempt}/{TOTP_ATTEMPTS}): ")
            step = match_totp(secret, code, ctx.clock.now(), None)
            if step is not None:
                break
            console.say("코드가 맞지 않습니다.")
        if step is None:
            raise AdminError("코드 확인에 실패했습니다. 아무것도 바꾸지 않았습니다.", EXIT_FAIL)

        codes = new_recovery_codes()
        with transaction(conn):
            cur = conn.execute(
                "UPDATE users SET totp_secret = ?, totp_last_step = ? WHERE id = ?",
                (secret, step, user["id"]),
            )
            if cur.rowcount != 1:
                raise AdminError("사용자를 찾지 못했습니다. 아무것도 바꾸지 않았습니다.", EXIT_FAIL)
            conn.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user["id"],))
            conn.executemany(
                "INSERT INTO recovery_codes (user_id, code_hash) VALUES (?, ?)",
                [(user["id"], recovery_code_hash(c)) for c in codes],
            )
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
            # 예전 인증 코드 실패 기록·계정 잠금도 지운다 (새 인증 앱으로 바로 로그인할 수 있게).
            conn.execute("DELETE FROM login_code_failures WHERE user_id = ?", (user["id"],))
            conn.execute("DELETE FROM login_code_locks WHERE user_id = ?", (user["id"],))

    console.say()
    console.say("✅ 2차 인증을 재설정했습니다. 모든 기기가 로그아웃되었습니다.")
    console.say("새 복구 코드 (지금 한 번만 보여 줍니다. 안전한 곳에 적어 두세요).")
    console.say("각 코드는 한 번만 쓸 수 있습니다:")
    for c in codes:
        console.say(f"  {c}")
    console.say("이 화면을 닫기 전에 복구 코드를 옮겨 적었는지 확인하세요.")
    return EXIT_OK


# ── set-password ────────────────────────────────────


def cmd_set_password(ctx: Context, args: argparse.Namespace) -> int:
    console = ctx.console
    _require_terminal(console)
    with ctx.connect() as conn:
        user = _single_user(conn)
        console.say(f"계정: {user['username']}")
        console.say("새 비밀번호를 입력합니다 (화면에 표시되지 않음).")
        console.say("바꾸면 모든 기기가 로그아웃됩니다.")
        first = console.read_secret("새 비밀번호: ")
        if not PASSWORD_MIN_LENGTH <= len(first) <= PASSWORD_MAX_LENGTH:
            raise AdminError(
                f"비밀번호는 {PASSWORD_MIN_LENGTH}~{PASSWORD_MAX_LENGTH}자여야 합니다. "
                "아무것도 바꾸지 않았습니다.",
                EXIT_FAIL,
            )
        second = console.read_secret("한 번 더: ")
        if first != second:
            raise AdminError("두 비밀번호가 다릅니다. 아무것도 바꾸지 않았습니다.", EXIT_FAIL)
        password_hash = hash_password(first)
        with transaction(conn):
            cur = conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user["id"])
            )
            if cur.rowcount != 1:
                raise AdminError("사용자를 찾지 못했습니다. 아무것도 바꾸지 않았습니다.", EXIT_FAIL)
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    console.say("✅ 비밀번호를 바꿨습니다. 모든 기기가 로그아웃되었습니다.")
    return EXIT_OK


# ── 검색 색인 ───────────────────────────────────────

# 스크랩마다 주제 이름을 줄바꿈으로 이은 값 (0003_scraps.sql 트리거와 같은 형식).
_COMPARE_SQL = """
SELECT s.title, s.memo, s.url, f.rowid AS fts_id,
       f.title AS f_title, f.memo AS f_memo, f.url AS f_url, f.topics AS f_topics,
       (SELECT coalesce(group_concat(t.name, char(10)), '')
          FROM scrap_topics st JOIN topics t ON t.id = st.topic_id
         WHERE st.scrap_id = s.id) AS topics
  FROM scraps s LEFT JOIN scraps_fts f ON f.rowid = s.id
"""
_REFILL_SQL = """
INSERT INTO scraps_fts (rowid, title, memo, url, topics)
SELECT s.id, s.title, s.memo, s.url,
       (SELECT coalesce(group_concat(t.name, char(10)), '')
          FROM scrap_topics st JOIN topics t ON t.id = st.topic_id
         WHERE st.scrap_id = s.id)
  FROM scraps s
"""


@dataclass
class FtsReport:
    integrity_ok: bool
    scraps: int
    rows: int
    missing: int = 0
    orphan: int = 0
    different: int = 0

    @property
    def ok(self) -> bool:
        return (
            self.integrity_ok
            and self.scraps == self.rows
            and not (self.missing or self.orphan or self.different)
        )

    def line(self) -> str:
        if self.ok:
            return f"✅ 검색 색인 정상: 스크랩 {self.scraps}개, 색인 {self.rows}행"
        detail = [f"스크랩 {self.scraps}개", f"색인 {self.rows}행"]
        if not self.integrity_ok:
            detail.insert(0, "FTS5 무결성 검사 실패")
        if self.missing:
            detail.append(f"색인에 없음 {self.missing}")
        if self.orphan:
            detail.append(f"색인에만 있음 {self.orphan}")
        if self.different:
            detail.append(f"내용 다름 {self.different}")
        return f"❌ 검색 색인 이상: {', '.join(detail)} → fts-rebuild 로 다시 만드세요"


def _topics_key(value: object) -> list[str]:
    return sorted(name for name in str(value or "").split("\n") if name)


def check_fts(conn: sqlite3.Connection) -> FtsReport:
    try:
        conn.execute("INSERT INTO scraps_fts (scraps_fts) VALUES ('integrity-check')")
        integrity_ok = True
    except sqlite3.DatabaseError:
        integrity_ok = False
    # 앱이 동시에 쓰고 있어도 같은 시점의 내용끼리 비교한다 (읽기 트랜잭션 하나).
    conn.execute("BEGIN")
    try:
        scraps = conn.execute("SELECT count(*) FROM scraps").fetchone()[0]
        try:
            rows = conn.execute("SELECT count(*) FROM scraps_fts").fetchone()[0]
            orphan = conn.execute(
                "SELECT count(*) FROM scraps_fts WHERE rowid NOT IN (SELECT id FROM scraps)"
            ).fetchone()[0]
        except sqlite3.DatabaseError:
            return FtsReport(False, scraps, -1)
        missing = different = 0
        try:
            for row in conn.execute(_COMPARE_SQL):
                if row["fts_id"] is None:
                    missing += 1
                    continue
                same_text = (row["title"], row["memo"], row["url"]) == (
                    row["f_title"],
                    row["f_memo"],
                    row["f_url"],
                )
                if not same_text or _topics_key(row["topics"]) != _topics_key(row["f_topics"]):
                    different += 1
        except sqlite3.DatabaseError:
            integrity_ok = False
    finally:
        conn.execute("COMMIT")
    return FtsReport(integrity_ok, scraps, rows, missing, orphan, different)


def rebuild_fts(conn: sqlite3.Connection) -> int:
    """색인을 지우고 스크랩 테이블에서 다시 채운다 (한 트랜잭션). 반환: 색인 행 수.

    색인 자체가 손상됐어도 되도록 표를 지우고 같은 정의(마이그레이션이 만든 그대로)로 다시 만든다.
    트리거는 `scraps` 등에 붙어 있으므로 그대로 남는다.
    """
    with transaction(conn):
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'scraps_fts'"
        ).fetchone()
        if row is None or not str(row[0]).upper().startswith("CREATE VIRTUAL TABLE"):
            raise AdminError("scraps_fts 정의를 찾지 못했습니다 (마이그레이션 상태 확인).")
        conn.execute("DROP TABLE scraps_fts")
        conn.execute(row[0])
        conn.execute(_REFILL_SQL)
        return conn.execute("SELECT count(*) FROM scraps_fts").fetchone()[0]


def cmd_fts_check(ctx: Context, args: argparse.Namespace) -> int:
    with ctx.connect() as conn:
        report = check_fts(conn)
    ctx.console.say(report.line())
    return EXIT_OK if report.ok else EXIT_FAIL


def cmd_fts_rebuild(ctx: Context, args: argparse.Namespace) -> int:
    with ctx.connect() as conn:
        rows = rebuild_fts(conn)
        ctx.console.say(f"검색 색인을 다시 만들었습니다 ({rows}행).")
        report = check_fts(conn)
    ctx.console.say(report.line())
    return EXIT_OK if report.ok else EXIT_FAIL


# ── ai-usage ────────────────────────────────────────


def cmd_ai_usage(ctx: Context, args: argparse.Namespace) -> int:
    days: int = args.days
    today = datetime.fromtimestamp(ctx.clock.now(), KST).date()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(days)]
    with ctx.connect() as conn:
        found = {
            r["day"]: (int(r["count"]), int(r["tokens"]))
            for r in conn.execute(
                "SELECT day, count, tokens FROM ai_usage_days WHERE day >= ? AND day <= ?",
                (dates[-1], dates[0]),
            )
        }
    s = ctx.settings
    console = ctx.console
    console.say(f"AI 사용량 (Asia/Seoul 날짜, 최근 {days}일)")
    # 한글은 화면에서 두 칸이라 너비를 그만큼 줄인다.
    console.say(f"{'날짜':<10}  {'요청':>4}  {'토큰':>11}")
    total_count = total_tokens = 0
    for day in dates:
        count, tokens = found.get(day, (0, 0))
        total_count += count
        total_tokens += tokens
        console.say(f"{day:<12}  {count:>6,}  {tokens:>13,}")
    console.say(f"{'합계':<10}  {total_count:>6,}  {total_tokens:>13,}")
    console.say(
        f"하루 상한: 요청 {s.ai_per_day:,}회 (AI_PER_DAY), "
        f"토큰 {s.ai_tokens_per_day:,} (AI_TOKENS_PER_DAY)"
    )
    return EXIT_OK


# ── 진입점 ──────────────────────────────────────────


class _KoreanHelpFormatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):  # type: ignore[no-untyped-def]
        return super().add_usage(usage, actions, groups, "사용법: " if prefix is None else prefix)


def _days(value: str) -> int:
    if not (value.isascii() and value.isdigit()) or not 1 <= int(value) <= AI_USAGE_MAX_DAYS:
        raise argparse.ArgumentTypeError(f"1~{AI_USAGE_MAX_DAYS} 사이의 정수를 넣으세요")
    return int(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="scrap-app 운영 관리 명령. 서버에서는 api 컨테이너 안에서 실행한다 "
        "(docker compose exec api python -m app.admin <명령>).",
        epilog="종료 코드: 0 성공·정상, 1 실패·이상·취소(바꾼 것 없음), 2 실행 환경·사용법 오류, "
        "130 Ctrl+C(바꾼 것 없음).",
        formatter_class=_KoreanHelpFormatter,
        add_help=False,
    )
    parser._optionals.title = "옵션"
    parser.add_argument("-h", "--help", action="help", help="이 도움말을 보여 주고 끝낸다")
    sub = parser.add_subparsers(dest="command", title="명령", metavar="<명령>", required=True)

    def add(name: str, help_text: str, func: Callable[..., int]) -> argparse.ArgumentParser:
        p = sub.add_parser(
            name,
            help=help_text,
            description=help_text,
            formatter_class=_KoreanHelpFormatter,
            add_help=False,
        )
        p._optionals.title = "옵션"
        p.add_argument("-h", "--help", action="help", help="이 도움말을 보여 주고 끝낸다")
        p.set_defaults(func=func)
        return p

    reset = add(
        "reset-2fa",
        "인증 앱과 복구 코드를 모두 잃었을 때 2차 인증을 새로 등록한다 (터미널 필수). "
        "코드 확인에 성공해야 저장하고, 복구 코드 10개를 새로 발급하며 모든 기기를 로그아웃한다.",
        cmd_reset_2fa,
    )
    reset.add_argument(
        "--light-background",
        action="store_true",
        help="밝은 배경 터미널용 QR (기본은 어두운 배경용으로 색을 뒤집어 출력)",
    )
    add(
        "set-password",
        f"비밀번호를 바꾼다 (터미널 필수, {PASSWORD_MIN_LENGTH}자 이상, 두 번 입력). "
        "모든 기기를 로그아웃한다.",
        cmd_set_password,
    )
    add("fts-check", "검색 색인(scraps_fts) 무결성 검사. 정상 0, 이상 1로 끝난다.", cmd_fts_check)
    add(
        "fts-rebuild",
        "검색 색인을 스크랩 테이블에서 다시 만든다 (한 트랜잭션). 끝나면 fts-check 와 같은 판정.",
        cmd_fts_rebuild,
    )
    usage = add("ai-usage", "날짜별 AI 요청 수·토큰 수를 보여 준다.", cmd_ai_usage)
    usage.add_argument(
        "--days",
        type=_days,
        default=AI_USAGE_DEFAULT_DAYS,
        help=f"오늘부터 거꾸로 며칠 (기본 {AI_USAGE_DEFAULT_DAYS})",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    console: Console | None = None,
    settings: Settings | None = None,
    clock: Clock | None = None,
) -> int:
    console = console or Console()
    args = build_parser().parse_args(argv)
    try:
        if settings is None:
            try:
                settings = load_settings()
            except ConfigError as exc:
                raise AdminError(f"설정 오류: {exc}") from None
        ctx = Context(console=console, settings=settings, clock=clock or Clock())
        return int(args.func(ctx, args))
    except AdminError as exc:
        console.warn(f"❌ {exc}")
        return exc.code
    except (KeyboardInterrupt, EOFError):
        console.warn("\n중단했습니다. 아무것도 바꾸지 않았습니다.")
        return EXIT_INTERRUPTED
    except sqlite3.Error as exc:
        # SQLite 오류 문구에는 값이 들어가지 않는다 (예: database is locked).
        console.warn(f"❌ DB 오류: {type(exc).__name__}: {str(exc)[:200]}")
        return EXIT_ENV


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
