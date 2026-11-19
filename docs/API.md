# API 명세

> 상태: **확정 (v1, 2026-11-19, Phase 1 UI 확정 후)** — 변경이 필요하면 빌더는 "API 변경 제안"으로 보고하고 마스터가 고친다.
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
{ "id": 1, "name": "유튜브", "domain_patterns": ["youtube.com", "youtu.be"], "is_default": false }
{ "id": 1, "name": "claude" }
```
- 목록(`GET /sources`, `GET /topics`)은 사용자가 정한 순서대로 반환한다.
- `is_default: true`인 출처(기본값 "일반사이트")는 정확히 1개이며 삭제할 수 없다 (403).
- 출처를 삭제하면 그 출처의 스크랩은 기본 출처로 옮겨진다. 주제를 삭제하면 스크랩에서 그 주제만 빠진다.

### Session
```json
{ "id": 1, "user_agent": "string", "created_at": "...", "last_seen_at": "...", "current": true }
```
`current`: 지금 요청을 보낸 기기의 세션이면 true.

## 인증 `/api/auth`
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/auth/status` | `{ "setup_required": bool, "logged_in": bool }` |
| POST | `/auth/setup` | 최초 가입 `{ username, password }` → `{ "qr_data_url": string, "secret": string }`. 사용자가 1명 이상이면 403 |
| POST | `/auth/setup/verify` | `{ code }` → `{ "recovery_codes": string[] }` (10개) + 세션 쿠키 발급(로그인 상태) |
| POST | `/auth/login` | `{ username, password }` → `{ "totp_required": true, "challenge_id": "..." }` |
| POST | `/auth/login/verify` | `{ challenge_id, code }` 또는 `{ challenge_id, recovery_code }` → 204 + 세션 쿠키 발급 |
| POST | `/auth/logout` | 현재 세션 삭제 |
| POST | `/auth/logout-all` | 모든 세션 삭제 |
| GET | `/auth/sessions` | 로그인된 기기 목록 → `[Session]` |
| DELETE | `/auth/sessions/{id}` | 특정 기기 로그아웃 |
| POST | `/auth/totp/reset` | 2차 인증 재설정 시작 `{ password, code }` → `{ "qr_data_url": string, "secret": string }`. 새 코드 확인 전까지 기존 TOTP·복구 코드가 계속 유효 |
| POST | `/auth/totp/reset/verify` | `{ code }` (새 TOTP 코드) → `{ "recovery_codes": string[] }`. 이때 새 TOTP로 교체되고 기존 복구 코드는 모두 폐기 |

## 스크랩 `/api/scraps`
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/scraps` | 목록. 쿼리: `q`, `source_id`, `topic_ids`(쉼표, **모두 포함 = AND**), `liked`, `due`(`upcoming`: 오늘~오늘+7일 / `past`: 오늘 이전), `sort`(`created`/`due`), `cursor`, `limit` |
| POST | `/scraps` | 생성 (Scrap에서 id·날짜 제외, `source_id`, `topic_ids` 사용). `liked`는 선택, 기본 false |
| GET | `/scraps/{id}` | 상세 |
| PATCH | `/scraps/{id}` | 부분 수정. `liked`는 받지 않는다 (좋아요는 `PUT /like`로만 — 다른 기기의 변경을 덮어쓰지 않기 위해) |
| DELETE | `/scraps/{id}` | 삭제 |
| PUT | `/scraps/{id}/like` | `{ "liked": bool }` → `{ "liked": bool }` (값 지정 방식, 반복 호출해도 결과 동일) |

목록 응답: `{ "items": [Scrap], "next_cursor": "string | null" }`

> 날짜 기준(`today`)은 서버 시간대 Asia/Seoul.

## 보조 기능
| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/meta/preview` | `{ url }` → `{ title, source_id }` (og:title, 출처 자동 판별. 제목을 못 가져오면 title은 null, `source_id`는 항상 숫자이며 판별 실패 시 기본 출처) |
| GET/POST/PATCH/DELETE | `/sources`, `/sources/{id}` | 출처 관리 (기본 출처 DELETE는 403) |
| PUT | `/sources/order` | `{ "ids": [3, 1, 2] }` 전체 순서 지정 → 204 |
| GET/POST/PATCH/DELETE | `/topics`, `/topics/{id}` | 주제 관리 |
| PUT | `/topics/order` | `{ "ids": [...] }` 전체 순서 지정 → 204 |

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

## 입력 규칙
- 출처·주제 이름: 앞뒤 공백 제거 후 1~30자, 같은 종류 안에서 중복 불가 → 위반 시 400
- 스크랩 `title`: 빈 문자열이면 서버가 `url`을 제목으로 저장한다
- 스크랩 `url`: http/https만 허용 → 그 외 400
- 비밀번호: 최소 10자 (가입·재설정)
- 로그인 실패 제한: 같은 IP에서 비밀번호 또는 코드 5회 연속 실패 시 일정 시간 429 (`error.code`: `too_many_attempts`)
- 날짜 판정(`due`, 마감 임박)은 서버 기준 Asia/Seoul. 프론트 표시도 같은 기준을 쓴다
