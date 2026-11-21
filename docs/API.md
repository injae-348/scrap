# API 명세

> 상태: **확정 (v1, 2026-11-19, Phase 1 UI 확정 후 / v1.1 2026-11-20: 인증 세부 규칙 추가 / v1.2 2026-11-20: 가입 토큰 / v1.3 2026-11-20: 스크랩·출처·주제·검색·제목 미리보기 세부 규칙 / v1.4 2026-11-21: 목록 응답의 메모 미리보기 / v1.5 2026-11-21: AI 세부 규칙)** — 변경이 필요하면 빌더는 "API 변경 제안"으로 보고하고 마스터가 고친다.
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

목록 응답: `{ "items": [ScrapListItem], "next_cursor": "string | null" }`

`ScrapListItem` (v1.4): Scrap에서 `memo`를 빼고 `memo_preview`(메모 앞부분 최대 300자, 문자 단위 — 메모가 비면 `""`)를 넣은 형식. 메모 전문은 `GET /scraps/{id}`에서만 받는다. `POST`·`PATCH` 응답과 `GET /scraps/{id}`는 지금처럼 전문이 든 Scrap이다.

> 날짜 기준(`today`)은 서버 시간대 Asia/Seoul.

## 보조 기능
| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/meta/preview` | `{ url }` → `{ title, source_id }` (og:title, 출처 자동 판별. 제목을 못 가져오면 title은 null, `source_id`는 항상 숫자이며 판별 실패 시 기본 출처) |
| GET/POST | `/sources` | 출처 목록·추가 |
| PATCH/DELETE | `/sources/{id}` | 출처 수정·삭제 (기본 출처 DELETE는 403) |
| PUT | `/sources/order` | `{ "ids": [3, 1, 2] }` 전체 순서 지정 → 204 |
| GET/POST | `/topics` | 주제 목록·추가 |
| PATCH/DELETE | `/topics/{id}` | 주제 수정·삭제 |
| PUT | `/topics/order` | `{ "ids": [...] }` 전체 순서 지정 → 204 |

## 스크랩·출처·주제 세부 규칙 (v1.3, 2026-11-20 Phase 5)

### 공통
- `/auth/*`의 인증 불필요 경로와 `GET /health`를 뺀 **등록된 모든 `/api/*`는 세션 필수** (없거나 만료 → 401 `unauthorized`). 새 라우트는 기본으로 인증이 걸리는 구조로 만든다. 등록되지 않은 경로는 인증과 상관없이 404.
- 경로의 id(`/scraps/{id}` 등)가 숫자가 아니면 400 `invalid_input`, 숫자지만 없는 id면 404 `not_found`.
- GET 요청은 상태를 바꾸지 않는다.
- 이 절의 엔드포인트(스크랩·출처·주제·`/meta/preview`)는 요청 본문에 정의되지 않은 필드가 있거나 타입이 다르면(`"1"`을 숫자로, `1`을 불리언으로 바꿔 주지 않음) 400 `invalid_input` (예: `PATCH /scraps/{id}`에 `liked`). 정의되지 않은 쿼리 매개변수는 무시한다.
- 입력 오류는 400 `invalid_input`, 이름 중복은 400 `duplicate_name`, 없는 id는 404 `not_found`, 기본 출처 삭제는 403 `default_source`.
- 요청 본문 상한: 앱 전체 1MB, 인증 불필요 경로는 16KB. 넘으면 413 `payload_too_large`. 세션이 필요한 경로는 세션 확인을 본문 읽기보다 먼저 한다 (세션 없음 → 본문 형식과 상관없이 401).
- 상한의 1MB·16KB는 1024 단위(1,048,576·16,384바이트).
- 오류 판정 순서: 요청 과다(429) → 출처 불일치(403 `origin_mismatch`) → 그다음은 경로에 따라
  - 세션 필요 경로: 세션 없음(401) → 본문 상한(413) → 입력 오류(400)
  - 인증 불필요 경로: 본문 상한 16KB(413) → 입력 오류(400)
  - 등록되지 않은 경로: 본문이 1MB를 넘으면 413, 아니면 404/405
- 시각(`created_at`, `updated_at`)은 `+09:00` 오프셋 ISO 8601.

### 기본 출처 (최초 마이그레이션에서 생성)
| 순서 | 이름 | `domain_patterns` | `is_default` |
|---|---|---|---|
| 1 | 유튜브 | `youtube.com`, `youtu.be` | false |
| 2 | X | `x.com`, `twitter.com` | false |
| 3 | 일반사이트 | (없음) | **true** |
| 4 | 당근 | `daangn.com` | false |
| 5 | 커뮤니티 | (없음) | false |

주제는 기본값 없이 비어 있는 상태로 시작한다.

### 출처 자동 판별
- URL의 호스트(소문자, 끝의 `.` 제거)가 패턴과 **같거나 `.패턴`으로 끝나면** 일치 (`www.youtube.com`, `m.youtube.com` → `youtube.com`). 포트는 무시한다.
- 여러 출처가 일치하면 더 긴 패턴이 이긴다. 일치하는 출처가 없으면 기본 출처.
- `POST /scraps`에서 `source_id`를 빼면 서버가 이 규칙으로 정한다. `PATCH`로 `url`만 바꿔도 출처는 바뀌지 않는다 (사용자가 고른 값을 유지).

### 출처·주제 관리
- `POST /sources` `{ name, domain_patterns? }` → 201 + Source (맨 뒤 순서). `PATCH /sources/{id}` `{ name?, domain_patterns? }` → 200 + Source. `is_default`는 바꿀 수 없다.
- `domain_patterns`: 각 항목은 앞뒤 공백 제거·소문자화한 호스트 이름(영문·숫자·`-`·`.`, 1~253자, 스킴·경로·포트 없이). 출처당 최대 20개, 같은 출처 안 중복은 하나로 합친다. **다른 출처에 이미 있는 패턴은 400** `duplicate_pattern`. 기본 출처의 패턴은 항상 빈 배열이며 넣으려 하면 400.
- `POST /topics` `{ name }` → 201 + Topic (맨 뒤 순서). `PATCH /topics/{id}` `{ name }` → 200 + Topic.
- 이름 중복 판정은 앞뒤 공백 제거 후 대소문자 무시 (`Claude`와 `claude`는 중복).
- `DELETE` → 204. 출처 삭제 시 그 출처의 스크랩은 기본 출처로, 주제 삭제 시 스크랩에서 그 주제만 빠진다 (스크랩의 `updated_at`은 바꾸지 않는다).
- `PUT /…/order`: `ids`는 현재 있는 id 전부를 한 번씩 담아야 한다. 빠지거나 중복·없는 id가 있으면 400.

### 스크랩 입력
- `url`: 앞뒤 공백 제거, 최대 2048자, `http`/`https` 스킴과 호스트가 있어야 한다. 중간에 공백·제어문자가 있거나 사용자 정보(`user:pass@`)가 들어 있으면 400. 같은 URL을 여러 번 저장할 수 있다.
- `title`: 앞뒤 공백 제거 후 최대 300자. 빠지거나 빈 문자열·`null`이면 `url`을 제목으로 저장 (PATCH도 같음).
- `memo`: 최대 100,000자, 기본 `""`.
- `source_id`: 있는 출처여야 한다 (없으면 400). POST에서는 선택(빼면 자동 판별), PATCH에서는 null 불가.
- `topic_ids`: 최대 20개, 중복은 하나로 합친다. 없는 주제 id가 있으면 400. 기본 `[]`. PATCH에 주면 전체 교체.
- `due_date`: `YYYY-MM-DD` 실제 날짜 또는 `null`. 기본 `null`.
- `liked`: POST에서만 선택(기본 false). 변경은 `PUT /scraps/{id}/like`.
- `updated_at`은 `PATCH`로 내용이 바뀔 때 갱신한다. 좋아요는 `updated_at`을 바꾸지 않는다.
- Scrap의 `topics`는 주제의 사용자 지정 순서로 반환한다.

### 스크랩 목록 `GET /scraps`
- `limit`: 1~100, 기본 30. `cursor`: 이전 응답의 `next_cursor`를 그대로 넘긴다 (형식은 서버 내부용). 잘못된 cursor, 다른 `sort`로 만든 cursor는 400.
- `sort=created`(기본): `created_at` 최신순, 같으면 `id` 큰 순. `sort=due`: `due_date` 이른 순, **마감일 없는 스크랩은 맨 뒤**, 같으면 `created_at` 최신순, 그다음 `id` 큰 순.
- `liked=true`는 좋아요만, `liked=false`는 좋아요 아닌 것만, 생략하면 전부.
- `source_id`, `topic_ids`(쉼표 구분 숫자, 최대 100개)는 형식이 틀리거나 개수를 넘으면 400. 없는 id는 오류 없이 결과가 비게 된다.
- `due=upcoming`: 오늘 ≤ `due_date` ≤ 오늘+7일. `due=past`: `due_date` < 오늘. 마감일 없는 스크랩은 둘 다에서 빠진다.
- 모든 조건은 AND로 결합한다.

### 검색 `q`
- 대상: 제목, 메모, URL, 주제 이름. 대소문자 무시, 부분 일치.
- 앞뒤 공백 제거 후 비어 있으면 무시, 200자를 넘거나 제어문자가 있으면 400.
- 공백으로 나눈 단어가 **모두** 들어 있는 스크랩을 찾는다 (10단어를 넘으면 400). 3글자 이상 단어는 FTS5 trigram 색인으로, 1~2글자 단어는 부분 문자열 비교로 찾는다. 따옴표·`*`·`OR` 같은 문자도 검색 문법이 아니라 글자 그대로 취급한다.
- 결과 순서는 `sort`를 따른다 (관련도 순 아님).

### 제목 미리보기 `POST /meta/preview`
- 요청 `url`은 스크랩 `url`과 같은 규칙으로 검사한다 (위반 → 400 `invalid_input`).
- 서버가 그 페이지를 가져와 제목을 찾는다: 유튜브(`youtube.com`·`youtu.be`)는 oEmbed, 그 외는 `og:title` → `twitter:title` → `<title>` 순. HTML 엔티티를 풀고 공백을 정리해 최대 300자.
- 가져오기 제한: `http`/`https`만, 포트는 80·443만(스크랩 저장은 포트 제한 없음), 리다이렉트 최대 5번(매번 같은 검사), 공인 IP가 아닌 주소(사설·루프백·링크로컬·예약 대역 등)로 풀리는 호스트는 가져오지 않는다. 전체 5초, HTML만, 본문은 앞부분 최대 1MB만 읽는다. 동시에 가져오는 요청 수를 제한하고, 이 엔드포인트만 분당 20회로 더 낮게 제한한다 (넘으면 429 `too_many_requests`).
- 가져오기에 실패하거나 제목이 없으면 오류가 아니라 200 `{ "title": null, "source_id": … }`.

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
  "results": [{ "scrap": "ScrapListItem", "reason": "왜 관련 있는지" }]
}
```

## AI 세부 규칙 (v1.5, 2026-11-21 Phase 7)

### 공통
- 세션 필수, 요청 본문 규칙(정의되지 않은 필드·타입 오류 → 400 `invalid_input`)은 스크랩 엔드포인트와 같다. 본문 상한도 앱 전체 1MB 그대로.
- Claude API는 서버에서만 부른다. 모델은 서버 설정(`ANTHROPIC_MODEL`, 기본 `claude-opus-5-5`)으로 정한다.
- AI가 돌려준 값은 저장하지 않는다. 프론트는 입력칸에 제안으로만 채우고, 사용자가 저장해야 남는다.
- **오류 판정 순서**: 요청 과다(공통 429) → 출처 불일치(403) → 세션 없음(401) → 본문 상한(413) → 입력 오류(400) → AI 사용 불가(503 `ai_unavailable`) → AI 요청 제한(429 `too_many_requests`) → 처리.
- **AI 사용 불가**: 서버에 `ANTHROPIC_API_KEY`가 없거나, `.env.example`의 자리표시자이거나, `sk-ant-`로 시작하지 않으면 앱은 정상 기동하고 `/ai/*`만 503 `ai_unavailable`. 키 값은 설정 출력·로그·오류 응답 어디에도 넣지 않는다.
- **AI 요청 제한** (`/ai/extract`·`/ai/search` 합산, 넘으면 429 `too_many_requests` + `Retry-After`):
  - 분당 10회 (서버 메모리, IP 무관 전체 합산)
  - 하루 200회 (Asia/Seoul 날짜 기준, DB에 저장해 재시작 후에도 유지)
  - 동시 처리 2개 (꽉 차면 429, `Retry-After: 5`)
  - 입력 오류(400)·`ai_unavailable`(503)는 횟수에 넣지 않는다.
  - 외부 페이지 가져오기는 이와 별도로 `/meta/preview`와 `/ai/extract`(본문을 가져오는 경우)를 합쳐 IP별 분당 20회로 제한한다 (넘으면 429 `too_many_requests`). 본문을 얻지 못한 채우기도 여기에는 센다. 제한 값은 서버 설정(`AI_PER_MINUTE`, `AI_PER_DAY`)으로 바꿀 수 있다.
- **AI 실패**: Claude API 오류·시간 초과·응답 형식 위반·답변 거부는 502 `ai_failed` ("AI 응답을 받지 못했어요. 잠시 후 다시 시도해 주세요."). 원인 상세(외부 API 오류 문구 등)는 응답에 넣지 않고 서버 로그에만 남긴다(키·본문·검색어는 로그에 쓰지 않는다).
- **AI 사용 한도 도달**: Claude API가 사용 한도·결제 문제로 요청을 받지 않으면 503 `ai_quota_exceeded` ("이번 달 AI 사용 한도에 도달했어요."). 언제 풀릴지 서버가 알 수 없으므로 `Retry-After`는 넣지 않는다. 판정은 SDK의 오류 종류로 먼저 나눈 뒤 오류 본문으로 확인한다:
  - 429 `rate_limit_error`이면서 오류 상세 코드가 `enforced_spend_limit_reached` (요금 등급별 월 상한)
  - 400 `invalid_request_error`이면서 메시지가 "You have reached your specified"로 시작 (Console에서 건 지출 한도)
  - 402 `billing_error` (결제·크레딧)
  - 400 `invalid_request_error`이면서 메시지에 "credit balance"가 들어 있음 (크레딧 소진, 방어적 판정)
  - 그 밖의 실패는 502 `ai_failed`. 한도 도달도 AI 요청 횟수(분·하루)에는 다른 실패처럼 센다. 서버 로그에는 원인 종류(`spend_limit`/`tier_cap`/`billing`/`credit`)만 남긴다. 이 경우는 SDK 자동 재시도 대상에서 빼도 된다.
- 처리 시간 상한: `/ai/extract` 60초, `/ai/search` 90초 (넘으면 502 `ai_failed`). 클라이언트 연결이 끊기면 서버는 다음 Claude 호출 전에 처리를 멈추고 499 `client_closed`로 끝낸다 (이미 센 횟수는 되돌리지 않는다).
- Claude가 안전상 이유로 답을 거부하면 같은 요청을 Anthropic이 정한 다른 Claude 모델로 한 번 더 처리할 수 있다 (서버 설정 `ANTHROPIC_FALLBACKS=0`으로 끈다).
- AI 출력(제목·메모·이유·요약)에서는 제어문자와 글자 방향 서식 문자를 지운다.
- AI가 받는 외부 페이지 본문과 스크랩 내용은 "데이터"로만 다룬다. 그 안의 지시문을 따르지 않도록 시스템 프롬프트에 명시하고, 응답은 정해진 JSON 형식으로만 받는다.

### AI로 채우기 `POST /ai/extract`
- 요청: `url`(스크랩 `url`과 같은 검사, 위반 → 400), `text`(선택, 붙여넣은 본문, 앞뒤 공백 제거 후 최대 50,000자 — 넘으면 400 `invalid_input`, NUL 등 제어문자는 `\n`·`\r`·`\t`만 허용, 빈 문자열은 없는 것으로 본다).
- `text`가 있으면 서버는 페이지를 가져오지 않고 `text`를 본문으로 쓴다. 붙여넣은 본문에는 최소 길이가 없다 (X 게시물처럼 짧은 글도 그대로 AI에 보내고 `content_fetched: true`). 아래 200자 기준은 서버가 가져온 본문에만 적용한다. 글자 수는 유니코드 코드 포인트 기준이다. 붙여넣은 본문도 가져온 본문과 같이 앞부분 최대 20,000자만 AI에 보낸다.
- `text`가 없으면 서버가 `url`의 본문을 가져온다. 가져오기 규칙은 제목 미리보기와 같다 (http/https, 포트 80·443, 공인 IP만, 리다이렉트 5번, 1MB, 같은 안전한 연결 구현 재사용). 시간 상한 10초. HTML에서 본문 텍스트를 뽑고(브라우저 없이), 앞부분 최대 20,000자를 AI에 보낸다.
- 유튜브(`youtube.com`·`youtu.be`) 링크는 본문을 가져오지 않는다 (붙여넣은 `text`가 없으면 곧바로 본문 없음 처리).
- 유튜브처럼 본문을 얻지 못한 경우의 `title`은 제목 미리보기 규칙(유튜브는 oEmbed)으로 가져온 값이다.
- **본문을 얻지 못하면** (가져오기 실패, HTML 아님, 뽑은 본문이 200자 미만) Claude를 부르지 않고 200 `{ "title": <미리보기 제목 또는 null>, "due_date": null, "memo": null, "topic_suggestions": [], "content_fetched": false }`. 이 경우는 AI 요청 횟수에 넣지 않는다.
- `content_fetched`: AI가 본문(가져온 것 또는 붙여넣은 것)을 보고 답했으면 true.
- 응답 값 규칙 (서버가 AI 응답을 검사·정리한다):
  - `title`: 제어문자 제거, 앞뒤 공백 제거, 최대 300자. 비면 null.
  - `due_date`: 실제 날짜 `YYYY-MM-DD`가 아니면 null. 서버는 오늘 날짜(Asia/Seoul)를 AI에 알려 "이번 주 금요일" 같은 상대 표현을 풀게 한다. 마감·신청 기한이 분명할 때만 채운다.
  - `memo`: 한국어 마크다운 요약, 최대 2,000자(넘으면 자른다). 비면 null. NUL 등 제어문자는 `\n`·`\t` 외 제거.
  - `topic_suggestions`: 최대 5개, 각 1~30자. **이미 있는 주제와 대소문자 무시로 같으면 그 주제의 실제 이름으로 바꿔 돌려준다.** 중복은 하나로. AI에는 현재 주제 목록을 알려 기존 주제를 우선 고르게 한다. 새 주제는 만들지 않는다 (프론트가 "새 주제 제안"으로 표시).

### AI 검색 `POST /ai/search`
- 요청: `query` 앞뒤 공백 제거 후 1~200자, 제어문자 금지 (위반 → 400 `invalid_input`).
- 서버는 Claude에 `search_scraps` 도구를 주고 도구 호출 루프를 돈다. 도구는 목록 검색(`q`, 같은 FTS 규칙)을 쓰며 한 번에 최대 20개 후보(`id`, 제목, URL, 출처, 주제, 마감일, 메모 앞 300자, 좋아요)를 돌려준다. 도구 호출은 최대 6회(동의어·관련어 검색 포함). 넘으면 도구 목록은 그대로 두고 이후 호출을 거절하는 결과와 함께 결론을 내게 하며, 그래도 계속 도구만 부르면 8번째 응답에서 502 `ai_failed`로 끝낸다. 도구의 검색어가 비어 있으면 목록과 같이 최신 20개를 돌려준다.
- 결과: 최대 10개, 관련 높은 순. 각 `scrap`은 **`ScrapListItem`**(목록 응답과 같은 형식). `reason`은 한국어 한 문장, 최대 200자.
- 서버는 AI가 고른 id 중 **이번 요청의 도구 결과에 실제로 나온 것만** 남긴다(없는 id·지어낸 id 제거). 응답 직전에 DB에서 다시 읽어 지워진 스크랩은 뺀다.
- 관련 스크랩이 없으면 200 `{ "answer": "관련 스크랩을 찾지 못했어요." 같은 문장, "results": [] }`.
- `answer`: 최대 500자.

### 프론트 표시
- 오류 문구: 503 `ai_unavailable` → "AI 기능을 사용할 수 없어요 (서버 설정 필요)", 503 `ai_quota_exceeded` → 서버 `message` ("이번 달 AI 사용 한도에 도달했어요.", 재시도 버튼 없이 `ai_unavailable`과 구분해 표시), 502 `ai_failed` → 서버 `message`, 429 → `Retry-After`를 보여 주고 다시 시도, 413 `payload_too_large`(AI 채우기) → "붙여넣은 본문이 너무 길어요."
- AI 요청은 수십 초 걸릴 수 있다. 진행 중 표시와 취소 버튼을 두고, 그동안 다른 입력을 막지 않는다.
- 메모 속 외부 링크는 링크 글자 옆에 실제 호스트를 함께 표시한다 (AI가 제안한 메모의 위장 링크 대비).

## 입력 규칙
- 출처·주제 이름: 앞뒤 공백 제거 후 1~30자, 같은 종류 안에서 중복 불가 → 위반 시 400
- 스크랩 `title`: 빈 문자열이면 서버가 `url`을 제목으로 저장한다
- 스크랩 `url`: http/https만 허용 → 그 외 400
- 비밀번호: 최소 10자 (가입·재설정)
- 로그인 실패 제한: 같은 IP에서 비밀번호 또는 코드 5회 연속 실패 시 일정 시간 429 (`error.code`: `too_many_attempts`)
- 날짜 판정(`due`, 마감 임박)은 서버 기준 Asia/Seoul. 프론트 표시도 같은 기준을 쓴다
