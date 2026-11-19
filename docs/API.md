# API 명세

> 상태: **초안** — Phase 1(UI) 확정 후 마스터 세션이 최종 확정한다.
> 프론트(`ui-builder`)와 백엔드(`backend-builder`)는 이 문서를 기준으로 작업한다. 변경은 마스터만 한다.

## 공통
- 기본 경로: `/api`
- 인증: 세션 쿠키 (HttpOnly). 프론트는 `credentials: 'include'`로 요청.
- 형식: JSON, 날짜는 ISO 8601 (`2026-12-31`, `2026-11-19T17:00:00+09:00`)
- 오류 응답: `{ "error": { "code": "string", "message": "사용자에게 보여줄 한국어 문구" } }`
- 상태 코드: 200 성공, 201 생성, 204 내용 없음, 400 입력 오류, 401 미인증, 403 금지, 404 없음, 429 요청 과다

## 데이터 형식

### Scrap
```json
{
  "id": 1,
  "url": "https://...",
  "title": "string",
  "memo": "string (마크다운, 장문 가능)",
  "source": { "id": 1, "name": "유튜브" },
  "topics": [{ "id": 1, "name": "claude" }],
  "liked": false,
  "due_date": "2026-12-31 | null",
  "created_at": "...",
  "updated_at": "..."
}
```

### Source / Topic
```json
{ "id": 1, "name": "유튜브", "domain_patterns": ["youtube.com", "youtu.be"] }
{ "id": 1, "name": "claude" }
```

## 인증 `/api/auth`
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/auth/status` | `{ "setup_required": bool, "logged_in": bool }` |
| POST | `/auth/setup` | 최초 가입 `{ username, password }` → TOTP 등록 정보(QR 이미지 data URL, secret) |
| POST | `/auth/setup/verify` | `{ code }` → 복구 코드 10개 반환, 로그인 상태가 됨 |
| POST | `/auth/login` | `{ username, password }` → `{ "totp_required": true, "challenge_id": "..." }` |
| POST | `/auth/login/verify` | `{ challenge_id, code }` 또는 `{ challenge_id, recovery_code }` → 세션 쿠키 발급 |
| POST | `/auth/logout` | 현재 세션 삭제 |
| POST | `/auth/logout-all` | 모든 세션 삭제 |
| GET | `/auth/sessions` | 로그인된 기기 목록 |
| DELETE | `/auth/sessions/{id}` | 특정 기기 로그아웃 |

## 스크랩 `/api/scraps`
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/scraps` | 목록. 쿼리: `q`, `source_id`, `topic_ids`(쉼표), `liked`, `due`(`upcoming`/`past`), `sort`(`created`/`due`), `cursor`, `limit` |
| POST | `/scraps` | 생성 (Scrap에서 id·날짜 제외, `source_id`, `topic_ids` 사용) |
| GET | `/scraps/{id}` | 상세 |
| PATCH | `/scraps/{id}` | 부분 수정 |
| DELETE | `/scraps/{id}` | 삭제 |
| POST | `/scraps/{id}/like` | 좋아요 토글 → `{ "liked": bool }` |

목록 응답: `{ "items": [Scrap], "next_cursor": "string | null" }`

## 보조 기능
| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/meta/preview` | `{ url }` → `{ title, source_id }` (og:title, 출처 자동 판별. 실패 시 title은 null) |
| GET/POST/PATCH/DELETE | `/sources`, `/sources/{id}` | 출처 관리 |
| GET/POST/PATCH/DELETE | `/topics`, `/topics/{id}` | 주제 관리 |

## AI `/api/ai`
| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/ai/extract` | `{ url, text? }` → 제안값. **저장하지 않음** |
| POST | `/ai/search` | `{ query }` → 관련 스크랩과 이유 |

`/ai/extract` 응답:
```json
{
  "title": "string | null",
  "due_date": "2026-12-31 | null",
  "memo": "요약 제안 | null",
  "topic_suggestions": ["claude", "공모전"],
  "content_fetched": true
}
```
`content_fetched: false`이면 프론트는 "본문 붙여넣기" 입력을 안내한다.

`/ai/search` 응답:
```json
{
  "answer": "한두 문장 요약",
  "results": [{ "scrap": "Scrap", "reason": "왜 관련 있는지" }]
}
```
