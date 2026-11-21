-- AI 요청 하루 상한의 기록 (app/ai/limits.py AiRequestLimiter, docs/API.md v1.5 "AI 요청 제한").
-- 날짜(Asia/Seoul, YYYY-MM-DD)마다 Claude API를 부른 요청 수. 재시작 후에도 하루 상한이 이어지게 DB에 둔다.
-- 분당 상한·동시 처리 수는 프로세스 메모리에 있다.
-- 새 테이블만 추가한다 (이전 이미지로 롤백해도 이 테이블을 모르는 코드가 그대로 동작한다).

CREATE TABLE ai_usage_days (
    day   TEXT    PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0
);
