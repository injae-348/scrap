# backend

FastAPI 앱. 진입점 `app.main:app`, 작업 디렉터리는 이 폴더(`backend/`).

## 로컬 실행
```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
mkdir -p data                       # 기본 DB 경로 ./data/dev.db 의 디렉터리 (자동 생성하지 않음)

# 로컬 http 개발용 예시. 비밀값은 고정값을 쓰지 않고 실행할 때마다 만든다.
# SITE_DOMAIN 은 넣지 않는다 (넣으면 운영으로 보고 COOKIE_SECURE=0·http 출처를 거부한다).
export SESSION_SECRET="$(openssl rand -hex 32)"
export SETUP_TOKEN="$(openssl rand -hex 32)"    # 최초 가입 화면에 입력할 토큰 (echo "$SETUP_TOKEN"으로 확인)
export COOKIE_SECURE=0                          # http://localhost 에서 쿠키가 오가게 (운영에서는 쓰지 않는다)
export ALLOWED_ORIGINS=http://localhost:5173    # Vite 개발 서버 출처
ENABLE_API_DOCS=1 .venv/bin/uvicorn app.main:app --reload
curl http://127.0.0.1:8000/api/health   # {"status":"ok"}
```
앱이 시작될 때 `app/migrations/`의 SQL을 순서대로 적용한다 (적용 기록: `schema_migrations` 테이블).

## 검사 (CI와 동일)
```sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
```

## 환경변수
| 이름 | 기본값 | 설명 |
|---|---|---|
| `SESSION_SECRET` | (필수) | 32자 이상 랜덤 문자열(`openssl rand -hex 32`). 없거나 `.env.example` 자리표시자이거나 32자 미만이면 앱이 시작되지 않는다. 세션 토큰 해시(HMAC) 키로 쓴다 → 바꾸면 모든 기기가 로그아웃된다 |
| `SETUP_TOKEN` | (없음) | 최초 가입(`/auth/setup`)에 필요한 토큰. `openssl rand -hex 32`로 만든다. 없음·자리표시자·저장소에 공개된 예시값·32자 미만·글자 종류 10개 미만·`SESSION_SECRET`과 같은 값이면 미설정으로 보고 가입이 403(`setup_token_not_configured`)으로 막힌다 (앱은 정상 기동). 가입을 마치면 지운다 — 남아 있으면 시작 때 경고 로그 |
| `SITE_DOMAIN` | (없음) | 예: `<이름>.duckdns.org`. 허용 출처 `https://<SITE_DOMAIN>` (CSRF Origin 검사). **있으면 운영으로 본다**: `COOKIE_SECURE=0`, https가 아닌 허용 출처, `ENABLE_API_DOCS=1` 중 하나라도 있으면 기동 거부 |
| `ALLOWED_ORIGINS` | (없음) | 쉼표 구분 추가 허용 출처. 로컬 개발용 (예: `http://localhost:5173`). 운영에서는 비워 둔다 |
| `COOKIE_SECURE` | 켜짐 | 정확히 `0`일 때만 쿠키 Secure를 끈다 (로컬 http 개발용, `SITE_DOMAIN` 없을 때만). 켜져 있으면 쿠키 이름에 `__Host-` 접두사 |
| `DB_PATH` | `./data/dev.db` | SQLite 파일 경로. 상위 디렉터리가 없으면 만들지 않고 `/api/health`가 503 |
| `ENABLE_API_DOCS` | (꺼짐) | `1`이면 `/api/docs`, `/api/redoc`, `/api/openapi.json` 노출. 로컬 개발 전용 (`SITE_DOMAIN`이 있으면 기동 거부) |

`ANTHROPIC_API_KEY`는 아직 사용하지 않는다 (Phase 7).

공통 요청 상한(IP별 분당 300회)은 환경변수로 바꾸지 않는다 (`app/config.py` `DEFAULT_REQUESTS_PER_MINUTE`).

## 운영 제약
- **uvicorn 워커는 1개로 고정한다** (`--workers 1`). 가입 대기·로그인 challenge·TOTP 재설정 대기,
  IP별 요청 제한, 진행 중인 시도 수는 프로세스 메모리에 있으므로 워커끼리 공유되지 않는다.
  가입 대기·challenge는 몇 분짜리라 프로세스가 다시 시작되면 처음부터 다시 진행한다.
  계정 단위 2단계 실패 기록과 잠금 시각은 DB(`login_code_failures`, `login_code_locks`)에 둔다.
- **마이그레이션은 추가 위주로 쓴다** (`app/migrations/NNNN_*.sql`, 번호 순 적용, 파일마다 한 트랜잭션).
  배포 실패 시 이전 이미지로 롤백되어도 DB는 새 스키마 그대로이므로, 이전 코드가 계속 동작하도록
  테이블·열·인덱스 추가만 하고 이름 변경·삭제·타입 변경은 하지 않는다. 꼭 필요하면 여러 배포에 나눠
  (추가 → 코드 전환 → 정리) 진행한다. 적용된 파일은 고치지 않고 새 번호로 만든다.

## 구조
- `app/config.py` 설정·기동 검사, `app/db.py` 연결·마이그레이션, `app/migrations/NNNN_*.sql`
- `app/auth/` 인증 API(`router.py`), 세션·쿠키(`sessions.py`), 비밀번호·TOTP·복구 코드(`crypto.py`)
- `app/csrf.py` Origin 검사, `app/headers.py` `/api/*` `Cache-Control: no-store`
- `app/ratelimit.py` 공통 요청 제한·로그인 실패 제한(IP별은 메모리, 계정 단위는 DB, 동시 요청 예약), `app/memstore.py` 메모리 임시 저장소
- 인증이 필요한 라우터는 `from app.auth import get_current_session`을 의존성으로 쓴다:
  `APIRouter(prefix="/api", dependencies=[Depends(get_current_session)])`
