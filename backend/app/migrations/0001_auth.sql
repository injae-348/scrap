-- Phase 4: 인증 테이블 (users, recovery_codes, sessions).
-- 시각은 ISO 8601 문자열(Asia/Seoul, 초 단위, 예: 2026-11-19T17:00:00+09:00)로 저장한다.
-- 같은 오프셋으로만 저장하므로 문자열 비교로 시간 순서를 비교할 수 있다.

CREATE TABLE users (
    id             INTEGER PRIMARY KEY,
    username       TEXT    NOT NULL UNIQUE,
    password_hash  TEXT    NOT NULL,             -- Argon2id (PHC 문자열)
    totp_secret    TEXT    NOT NULL,             -- base32
    totp_last_step INTEGER,                      -- 마지막으로 받은 TOTP 구간(unix초 // 30). 재사용 방지
    created_at     TEXT    NOT NULL
);

CREATE TABLE recovery_codes (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    code_hash  TEXT    NOT NULL,                 -- SHA-256(정규화한 코드) hex
    used_at    TEXT                              -- NULL이면 아직 안 씀
);
CREATE INDEX recovery_codes_user_id ON recovery_codes (user_id);
CREATE INDEX recovery_codes_code_hash ON recovery_codes (code_hash);

-- AUTOINCREMENT: 삭제한 세션 id를 새 세션에 다시 쓰지 않는다 (기기 목록·개별 로그아웃에서 id 혼동 방지).
CREATE TABLE sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash   TEXT    NOT NULL UNIQUE,        -- HMAC-SHA256(SESSION_SECRET 파생 키, 토큰) hex
    user_agent   TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL,
    last_seen_at TEXT    NOT NULL
);
CREATE INDEX sessions_user_id ON sessions (user_id);
