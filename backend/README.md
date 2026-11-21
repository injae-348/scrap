# backend

FastAPI 앱. 진입점 `app.main:app`, 작업 디렉터리는 이 폴더(`backend/`).

## 로컬 실행
```sh
python3.12 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-dev.txt   # 런타임 + 개발 의존성 (해시 검증)
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

- SQLite는 FTS5 `trigram` 토크나이저가 되는 **3.34 이상**이어야 한다 (아니면 마이그레이션이 실패해 `/api/health`가 503). 확인: `.venv/bin/python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute(\"CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')\"); print(sqlite3.sqlite_version, 'ok')"`
- 스크랩 API를 손으로 시험하려면 `ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:8000`(문서 화면 출처 추가)으로 바꿔 위처럼 `ENABLE_API_DOCS=1`로 띄우고, 같은 브라우저에서 가입(`POST /api/auth/setup` → `/setup/verify`, 인증 앱 코드)한 뒤 `http://127.0.0.1:8000/api/docs`에서 `/api/scraps`·`/api/meta/preview` 등을 호출한다 (세션 쿠키가 그대로 쓰인다. `/meta/preview`는 실제 외부 요청을 보낸다 — 테스트는 가짜 DNS·연결을 쓴다).

## 검사 (CI와 동일)
```sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
# 알려진 취약점 검사 (PyPI 취약점 DB 조회, 네트워크 필요)
.venv/bin/pip-audit --strict --require-hashes --disable-pip -r requirements.txt
.venv/bin/pip-audit --strict --require-hashes --disable-pip -r requirements-dev.txt
```

## 의존성
직접 의존성은 `.in` 파일에 적고, 하위 의존성까지 버전·해시를 고정한 `.txt`는 [uv](https://docs.astral.sh/uv/)로 만든다.

| 파일 | 내용 |
|---|---|
| `requirements.in` | 런타임 직접 의존성 (api 이미지) |
| `requirements.txt` | ↑ 하위 의존성까지 고정 + 해시 (생성 파일, 직접 고치지 않는다) |
| `requirements-dev.in` | 개발·CI 직접 의존성 (`-r requirements.in`, `-c requirements.txt`) |
| `requirements-dev.txt` | ↑ 런타임 + 개발 의존성 전부 고정 + 해시 (생성 파일) |

`.in`을 고친 뒤 이 순서로 다시 만든다 (`backend/`에서, 운영은 linux/amd64지만 `--universal`이라 macOS 개발 환경에서도 같은 파일을 쓴다):
```sh
uv pip compile --universal --python-version 3.12 --generate-hashes requirements.in -o requirements.txt
uv pip compile --universal --python-version 3.12 --generate-hashes requirements-dev.in -o requirements-dev.txt
```
- 버전을 올릴 때: `.in`의 `==` 값을 바꾸거나, 하위 의존성만 올리려면 위 명령에 `--upgrade-package <이름>`을 붙인다.
- 이미지(`Dockerfile`)는 `pip install --require-hashes --no-deps -r requirements.txt`로 설치한다 → 목록에 없거나 해시가 다른 패키지는 설치되지 않는다.
- `requirements-dev.txt`는 런타임 의존성을 모두 포함하므로 개발 환경은 이 파일 하나만 설치한다 (해시 모드에서는 모든 줄에 해시가 있어야 해서 `-r requirements.txt`를 섞지 않는다).
- 런타임 코드가 직접 import하는 패키지(`httpcore`, `certifi` 등)는 `requirements.in`에 직접 적는다. `httpx`는 테스트(`TestClient`)에서만 쓰므로 `requirements-dev.in`에 있다.
- `opentelemetry-api`는 FastAPI의 필수 의존성이라(FastAPI 내장 미들웨어가 import) 잠금 파일에 들어간다.
- uvicorn은 `uvicorn[standard]` 대신 `uvicorn` + `httptools` + `uvloop`만 쓴다 (websockets·watchfiles·python-dotenv·PyYAML 제외). `--reload`(watchfiles)는 개발에서 필요할 때만 따로 설치한다.
- 무거운 의존성(헤드리스 브라우저, BeautifulSoup 같은 추가 파서, 대형 ML 라이브러리)은 넣지 않는다 (1GB 서버).
  예외: AI 본문 추출용 `trafilatura`(lxml 기반)는 Phase 7 계획대로 넣었다. 처음 쓸 때만 불러온다.
- `anthropic`(Claude API SDK)은 자체 HTTP 클라이언트(`httpx2`)로 Anthropic API만 부른다. 이 SDK도 키가 유효하고
  AI 요청이 처음 올 때만 불러온다 (불러오면 프로세스 메모리가 약 40MB 늘어난다).

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

| `ANTHROPIC_API_KEY` | (없음) | Claude API 키. 없음·`.env.example` 자리표시자(`sk-ant-xxxx`)·`sk-ant-`로 시작하지 않음 → 앱은 정상 기동, `/api/ai/*`만 503 `ai_unavailable`. 값은 설정 출력·로그·오류 응답에 넣지 않는다 |
| `ANTHROPIC_MODEL` | `claude-opus-5-5` | AI 기능이 쓰는 모델. 형식이 틀리면 기본값 + 경고 로그 |
| `AI_PER_MINUTE` | `10` | AI 요청(`/ai/extract`·`/ai/search` 합산) 분당 상한 (메모리). 1 이상 정수, 틀리면 기본값 |
| `ANTHROPIC_FALLBACKS` | 켜짐 | 거부 시 Anthropic이 정한 다른 Claude 모델로 다시 처리(서버측 fallbacks 베타). 정확히 `0`이면 베타 헤더와 `fallbacks`를 모두 빼고 설정한 모델에서만 처리한다 |
| `AI_PER_DAY` | `200` | AI 요청 하루 상한 (Asia/Seoul 날짜, DB `ai_usage_days`). 1 이상 정수, 틀리면 기본값 |

`ANTHROPIC_LOG`(SDK 디버그 로그)는 운영에서 켜지 않는다.

공통 요청 상한(IP별 분당 300회)은 환경변수로 바꾸지 않는다 (`app/config.py` `DEFAULT_REQUESTS_PER_MINUTE`).
서버가 사용자 URL을 가져오는 요청(`/meta/preview`, `/ai/extract`의 페이지 가져오기)은 합쳐서 IP별 분당 20회다 (`app.state.fetch_limiter`).

## 운영 제약
- **uvicorn 워커는 1개로 고정한다** (`--workers 1`). 가입 대기·로그인 challenge·TOTP 재설정 대기,
  IP별 요청 제한, 진행 중인 시도 수는 프로세스 메모리에 있으므로 워커끼리 공유되지 않는다.
  가입 대기·challenge는 몇 분짜리라 프로세스가 다시 시작되면 처음부터 다시 진행한다.
  계정 단위 2단계 실패 기록과 잠금 시각은 DB(`login_code_failures`, `login_code_locks`)에 둔다.
- **마이그레이션은 추가 위주 (컬럼·테이블 삭제·이름 변경 금지, 필요하면 두 배포에 걸쳐 단계적으로)**.
  (`app/migrations/NNNN_*.sql`, 번호 순 적용, 파일마다 한 트랜잭션.)
  배포 실패 시 이전 이미지로 롤백되어도 DB는 새 스키마 그대로이므로, 이전 코드가 계속 동작하도록
  테이블·열·인덱스·트리거 추가만 하고 이름 변경·삭제·타입 변경은 하지 않는다. 꼭 필요하면 여러 배포에 나눠
  (추가 → 코드 전환 → 정리) 진행한다. 적용된 파일은 고치지 않고 새 번호로 만든다.
  새로 추가하는 NOT NULL 열에는 기본값을 둔다 (이전 코드의 INSERT가 깨지지 않게).

## 구조
- `app/config.py` 설정·기동 검사, `app/db.py` 연결·마이그레이션, `app/migrations/NNNN_*.sql`
- `app/routing.py` **인증 기본 거부**: 공개 엔드포인트 목록(6개)과 세션 필수 상위 라우터, 기동 시 전수 검사
- `app/auth/` 인증 API(`router.py`: 공개 `public_router` / 세션 필수 `router`), 세션·쿠키(`sessions.py`), 비밀번호·TOTP·복구 코드(`crypto.py`)
- `app/scraps.py` 스크랩 CRUD·목록·좋아요, `app/search.py` 검색어 → FTS5/LIKE 조건
- `app/sources.py` 출처 CRUD·자동 판별, `app/topics.py` 주제 CRUD, `app/ordering.py` 순서 지정
- `app/fetch.py` **사용자 URL 가져오기 공통 모듈** (`SafeFetcher`: IP 고정 연결·포트 80/443·공인 IP만·리다이렉트 재검사·크기/시간 상한·동시 수 제한). 사용자 URL은 이 모듈로만 가져온다 (다른 HTTP 클라이언트·trafilatura 내장 가져오기 금지, `tests/test_fetch.py`가 검사), `app/netguard.py` 공인 IP 판정
- `app/meta.py` 제목 미리보기 API, `app/preview.py` 제목 추출(oEmbed·og:title 등)
- `app/pagetext.py` AI로 채우기용 본문 추출 (trafilatura, HTML 문자열만 넘김. 파싱 전에 스크립트 등 블록을 덜어 내고 태그 수·입력 길이 상한을 둔다), `app/parsing.py` 파싱 전용 동시 실행 제한 (시간 초과로 기다림이 끝나도 파싱 스레드가 끝날 때까지 자리를 쥔다)
- `app/ai/` AI API: `router.py`(`/ai/extract`·`/ai/search`), `claude.py`(Claude 호출·재시도·오류 분류, 클라이언트 지연 생성), `prompts.py`(고정 시스템 프롬프트·JSON 스키마·`search_scraps` 도구), `limits.py`(분·하루·동시 제한)
- `app/validation.py` 공통 입력 검사 (URL 검사는 스크랩 저장과 미리보기가 같은 함수를 쓴다)
- `app/guard.py` 요청 본문 상한(앱 1MB, 인증 불필요 경로 16KB → 413)과 세션 사전 확인(세션 필요 경로는 본문을 읽기 전에 401)
- `app/csrf.py` Origin 검사, `app/headers.py` `/api/*` `Cache-Control: no-store`
- `app/ratelimit.py` 공통 요청 제한·로그인 실패 제한(IP별은 메모리, 계정 단위는 DB, 동시 요청 예약), `app/memstore.py` 메모리 임시 저장소

### 새 API 라우터 추가 (인증 기본 거부)
`/api/*`는 공개 6개(`GET /health`, `GET /auth/status`, `POST /auth/setup`, `POST /auth/setup/verify`,
`POST /auth/login`, `POST /auth/login/verify`)를 빼고 모두 세션이 필요하다.
1. 모듈에 `router = APIRouter(prefix="/<이름>")`를 만든다 (`/api`·인증 의존성은 붙이지 않는다).
2. `app/main.py`의 `PROTECTED_ROUTERS`에 추가한다 → 세션 필수 상위 라우터(`/api`) 아래에 붙는다.
3. 세션 값이 필요하면 라우트 인자로 `session: CurrentSession = Depends(get_current_session)`를 받는다
   (같은 요청 안에서 한 번만 실행된다).

라우터 바깥의 `RequestGuardMiddleware`(`app/guard.py`)가 같은 기준(라우트의 세션 의존성)으로 세션을 먼저 확인하므로,
세션이 없으면 본문을 읽기 전에 401이 된다. 등록되지 않은 경로는 인증과 상관없이 404다.

`create_app()`은 마지막에 `assert_default_deny()`로 등록된 모든 `/api/*` 라우트를 검사해, 공개 목록 밖인데
세션 의존성이 없는 라우트가 있으면 기동을 거부한다 (`tests/test_default_deny.py`가 모든 라우트를 쿠키 없이 호출해 401을 확인한다).
공개 엔드포인트를 늘리려면 `docs/API.md`부터 바꾼다.

### 검색 색인
`scraps_fts`(FTS5, `tokenize='trigram'`)는 `0003_scraps.sql`의 트리거가 스크랩 생성·수정·삭제, 스크랩의 주제 변경,
주제 이름 변경·삭제 때 자동으로 맞춘다. 앱 코드에서 색인을 직접 고치지 않는다.
