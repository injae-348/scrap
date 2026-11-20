# API 명세

> 상태: **확정 (v1, 2026-11-19, Phase 1 UI 확정 후 / v1.1 2026-11-20: 인증 세부 규칙 추가 / v1.2 2026-11-20: 가입 토큰)** — 변경이 필요하면 빌더는 "API 변경 제안"으로 보고하고 마스터가 고친다.
> 프론트(`ui-builder`)와 백엔드(`backend-builder`)는 이 문서를 기준으로 작업한다. 변경은 마스터만 한다.

## 공통
- 기본 경로: `/api`
- 인증: 세션 쿠키 (HttpOnly). 프론트는 `credentials: 'include'`로 요청.
- 형식: JSON, 날짜는 ISO 8601 (`2026-12-31`, `2026-11-19T17:00:00+09:00`)
- 오류 응답: `{ "error": { "code": "string", "message": "사용자에게 보여줄 한국어 문구" } }`
- 상태 코드: 200 성공, 201 생성, 204 내용 없음, 400 입력 오류(FastAPI 기본 422 대신), 401 미인증, 403 금지, 404 없음, 405 허용되지 않은 메서드, 429 요청 과다, 500 서버 오류(`internal_error`), 503 일시적 사용 불가(헬스체크에서 DB를 쓸 수 없음, `db_unavailable`)

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

## 상태 확인
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/health` | 인증 불필요. `{ "status": "ok" }` (200). 배포 후 헬스체크용 — DB 연결까지 확인한다 |

## 인증 `/api/auth`
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/auth/status` | `{ "setup_required": bool, "logged_in": bool }` |
| POST | `/auth/setup` | 최초 가입 `{ username, password, setup_token }` → `{ "qr_data_url": string, "secret": string }`. 사용자가 1명 이상이면 403. `setup_token`은 서버 `.env`의 `SETUP_TOKEN`과 같아야 한다 (아래 세부 규칙) |
| POST | `/auth/setup/verify` | `{ code }` → `{ "recovery_codes": string[] }` (10개) + 세션 쿠키 발급(로그인 상태) |
| POST | `/auth/login` | `{ username, password }` → `{ "totp_required": true, "challenge_id": "..." }` |
| POST | `/auth/login/verify` | `{ challenge_id, code }` 또는 `{ challenge_id, recovery_code }` → 204 + 세션 쿠키 발급 |
| POST | `/auth/logout` | 현재 세션 삭제 |
| POST | `/auth/logout-all` | 모든 세션 삭제 |
| GET | `/auth/sessions` | 로그인된 기기 목록 → `[Session]` |
| DELETE | `/auth/sessions/{id}` | 특정 기기 로그아웃 |
| POST | `/auth/totp/reset` | 2차 인증 재설정 시작 `{ password, code }` → `{ "qr_data_url": string, "secret": string }`. 새 코드 확인 전까지 기존 TOTP·복구 코드가 계속 유효 |
| POST | `/auth/totp/reset/verify` | `{ code }` (새 TOTP 코드) → `{ "recovery_codes": string[] }`. 이때 새 TOTP로 교체되고 기존 복구 코드는 모두 폐기. **현재 기기를 뺀 다른 세션은 모두 로그아웃**된다 (휴대폰 분실 대비) |

### 인증 세부 규칙 (v1.1, 2026-11-20 Phase 4)
- **인증 불필요 경로**: `GET /health`, `GET /auth/status`, `POST /auth/setup`, `POST /auth/setup/verify`, `POST /auth/login`, `POST /auth/login/verify`. 나머지 `/api/*`는 세션이 없거나 만료되면 401 (`unauthorized`).
- **가입 확정 시점**: 사용자는 `/auth/setup/verify`가 성공해야 생긴다. `setup_required`는 "확정된 사용자가 0명"일 때 true.
  - `/auth/setup`은 가입 대기 정보(아이디·비밀번호 해시·TOTP 비밀값)를 서버에 잠시(10분) 보관하고, 이를 요청한 브라우저에만 HttpOnly 쿠키로 묶는다. `/auth/setup/verify`는 그 쿠키가 있어야 한다 (없거나 만료 → 400 `setup_expired`).
  - 대기 중에 `/auth/setup`을 다시 부르면 새 대기 정보로 바뀐다 (가입을 중간에 그만둔 경우 다시 시작).
  - 가입 대기에 틀린 코드를 5번 넣으면 대기 정보를 폐기한다 → 이후 400 `setup_expired` (처음부터 다시).
  - 확정된 사용자가 있으면 `/auth/setup`, `/auth/setup/verify` 모두 403 (`setup_disabled`).
- **가입 토큰 (`SETUP_TOKEN`, v1.2)**: 도메인은 인증서 공개 기록(CT 로그)으로 이미 알려져 있으므로, 서버 `.env`에만 있는 토큰을 아는 사람만 가입할 수 있게 한다.
  - 서버에 `SETUP_TOKEN`이 없거나, `.env.example`의 자리표시자이거나, 32자 미만이면 가입을 받지 않는다 → `/auth/setup` 403 (`setup_token_not_configured`). 이때도 앱은 정상 기동한다 (가입 후에는 토큰을 지우는 것이 정상 상태이므로).
  - `setup_token`이 없거나 다르면 403 (`invalid_setup_token`). 비교는 상수 시간으로 하고, 비밀번호 해시 계산 전에 검사한다. 틀린 토큰은 로그인 실패 제한(5회 → 15분 429)에 함께 센다.
  - 검사 순서: 확정 사용자 있음(`setup_disabled`) → 토큰 미설정 → 실패 잠금(429) → 토큰 불일치 → 입력값 검사 (아이디·비밀번호 누락·길이 오류도 토큰 검사 뒤에 400). 깨진 JSON·필드 타입 오류는 이보다 먼저 400.
  - `/auth/setup/verify`는 토큰을 다시 받지 않는다 (가입 대기 쿠키로 묶여 있음).
  - 가입 후에도 `SETUP_TOKEN`이 남아 있으면 앱 시작 때 "지워도 된다"는 경고 로그를 남긴다 (값은 로그에 쓰지 않는다).
- **로그인 2단계**: `challenge_id`는 5분 유효, 1회용. 틀린 코드를 5번 넣으면 그 challenge는 폐기된다 (400 `challenge_expired` → 처음부터 다시). 아이디나 비밀번호가 틀리면 어느 쪽이 틀렸는지 알려 주지 않는다 (401 `invalid_credentials`). 틀린 TOTP·복구 코드는 401 `invalid_code`.
- **TOTP**: 30초 간격 6자리, 앞뒤 1구간 허용. 이미 쓴 코드(같은 구간)는 다시 받지 않는다.
- **복구 코드**: 10개, 1회용. 대소문자·하이픈·공백은 무시하고 비교한다.
- **세션 쿠키**: HttpOnly, Secure, SameSite=Lax, Path=/, Max-Age 400일. 요청마다 세션이 확인되면 쿠키 만료를 갱신하고 `last_seen_at`을 갱신한다(잦은 쓰기를 피하려 최소 간격을 둘 수 있음). **180일 동안 쓰지 않은 세션은 만료**되어 401.
  - 쿠키 이름: 세션 `__Host-session`, 가입 대기 `__Host-setup`. 로컬 http 개발(`COOKIE_SECURE=0`)에서만 접두사 없이 `session`, `setup`.
  - `/api/*` 응답은 모두 `Cache-Control: no-store` (브라우저·서비스워커가 인증 응답을 캐시하지 않게).
- **로그아웃**: `/auth/logout`, `/auth/logout-all`, `DELETE /auth/sessions/{id}`는 204. `logout-all`은 현재 기기 포함 전부 삭제한다. 다른 사람의/없는 세션 id는 404.
- **CSRF**: GET·HEAD·OPTIONS가 아닌 `/api/*` 요청에 `Origin` 헤더가 있으면 허용 출처(`https://<SITE_DOMAIN>`, 개발용 `ALLOWED_ORIGINS`)와 같아야 한다. 다르면 403 (`origin_mismatch`). `Origin`이 없으면 `Sec-Fetch-Site`가 없거나 `same-origin`일 때만 허용.
- **요청 제한** (IP별 제한은 서버 메모리, 계정 단위 제한은 DB에 저장해 재시작 후에도 유지):
  - 로그인 실패: 비밀번호·TOTP·복구 코드·`/auth/totp/reset`의 비밀번호/코드 실패를 합쳐 5회 연속 실패하면 15분 동안 이 엔드포인트들이 429 (`too_many_attempts`). 2단계(TOTP·복구 코드)까지 성공해야 횟수 초기화. 동시에 보낸 요청도 5회를 넘겨 평가되지 않는다.
  - 계정 단위(모든 IP 합산): 2단계 코드(TOTP·복구 코드) 실패가 15분 안에 10회가 되면 15분 동안 `/auth/login/verify`가 IP와 상관없이 429 (`too_many_attempts`). 비밀번호가 새어 나간 상태에서 IP를 바꿔 가며 코드를 추측하는 것을 막는다 (그동안 본인도 로그인할 수 없다 → 비밀번호 유출 신호). 2단계 성공으로 이 기록은 지워지지 않고 15분이 지나야 빠지며, 잠금이 끝나면 새로 센다.
  - IP 기준: IPv4는 주소 하나, IPv6는 /64 단위로 센다 (IPv4-mapped IPv6는 IPv4로 바꿔 센다).
  - 공통: 모든 `/api/*`(health 포함)에 분당 상한을 둔다. 넘으면 429 (`too_many_requests`).
  - 동시 요청이 남은 시도 횟수를 모두 차지하고 있으면 잠금 전이라도 429 `too_many_attempts` (`Retry-After: 1`). challenge·가입 대기의 5회 상한이 진행 중인 요청으로 찼을 때는 400 `challenge_expired` / `setup_expired`.
  - 비밀번호 해시 계산 대기가 2초를 넘으면 429 `too_many_requests` (`Retry-After: 1`, 실패 횟수에는 넣지 않음).
  - 429 응답에는 `Retry-After`(초) 헤더를 넣는다.
- **오류 코드 정리**:
  - 401 `unauthorized`: 세션 없음·만료. **프론트는 이 코드일 때만 "로그인 필요"로 처리**한다 (다른 401은 입력 오류 안내).
  - 401 `invalid_credentials`: 로그인·`/auth/totp/reset`의 틀린 아이디/비밀번호.
  - 401 `invalid_code`: 틀린 TOTP·복구 코드 (로그인, 가입 확정, 재설정 시작·확정).
  - 400 `setup_expired` / `challenge_expired` / `totp_reset_expired`: 대기 정보 없음·만료 → 처음부터 다시.
  - 400 `invalid_input`: `login/verify`에 `code`와 `recovery_code`를 둘 다 보내거나 둘 다 뺀 경우 등.
- **입력 규칙(인증)**: 아이디는 앞뒤 공백 제거 후 1~64자, 제어문자 금지. 비밀번호는 10~1024자.
- **복구 코드 형식**: `XXXX-XXXX-XXXX-XXXX` (16자, 0/O/1/I 제외한 영숫자).
- **세션 목록**: `last_seen_at` 최신순. 시각은 `+09:00` 오프셋 ISO 8601. `DELETE /auth/sessions/{현재 id}`는 현재 기기 로그아웃과 같다 (쿠키 삭제).
- **운영 설정 가드**: `SITE_DOMAIN`이 설정돼 있는데(운영) `COOKIE_SECURE=0`이거나 `ALLOWED_ORIGINS`에 `https`가 아닌 출처가 있으면 앱이 시작되지 않는다. `SETUP_TOKEN`은 공개된 예시값이거나, 서로 다른 글자가 10개 미만이거나, `SESSION_SECRET`과 같으면 미설정으로 본다. `SITE_DOMAIN`이 있으면 운영으로 본다 (로컬 개발에서는 `SITE_DOMAIN`을 넣지 않는다). 운영에서 `ENABLE_API_DOCS=1`이어도 앱이 시작되지 않는다.
- **기동 조건**: `SESSION_SECRET`이 없거나 `.env.example`의 자리표시자이거나 32자 미만이면 앱이 시작되지 않는다.

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
