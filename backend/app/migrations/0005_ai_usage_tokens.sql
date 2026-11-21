-- AI 하루 토큰 예산의 기록 (app/ai/limits.py, docs/API.md v1.6 "하루 토큰 예산").
-- 날짜(Asia/Seoul)마다 Claude 응답 usage 합계
-- (input_tokens + cache_creation_input_tokens + cache_read_input_tokens + output_tokens).
-- 열만 추가한다: 기본값이 있으므로 이 열을 모르는 이전 코드의 INSERT (day, count) 도 그대로 동작한다.

ALTER TABLE ai_usage_days ADD COLUMN tokens INTEGER NOT NULL DEFAULT 0;
