-- 계정 단위 2단계(TOTP·복구 코드) 실패 상한의 기록 (app/ratelimit.py AccountAttemptLimiter).
-- 진행 중인 시도(예약)는 메모리에 두고, 확정된 실패와 잠금 시각만 여기에 둔다.
-- 시각은 내부 계산용이라 화면에 보이지 않으므로 유닉스 시각(초, REAL)으로 저장한다.

CREATE TABLE login_code_failures (
    id        INTEGER PRIMARY KEY,
    user_id   INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    failed_at REAL    NOT NULL
);
CREATE INDEX login_code_failures_user_failed_at ON login_code_failures (user_id, failed_at);

-- 사용자마다 마지막 잠금의 끝 시각. 잠금이 끝난 뒤에도 남겨 두고,
-- 그 시각 이전의 실패는 다시 세지 않는다 (잠금이 끝나면 새로 센다).
CREATE TABLE login_code_locks (
    user_id      INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    locked_until REAL    NOT NULL
);
