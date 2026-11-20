# 스크랩 관리 앱 (개인용 Raindrop 대체)

## 프로젝트 개요
- 혼자 쓰는 북마크/스크랩 관리 웹앱. 아이폰(PWA, Safari 홈 화면 추가)과 PC 브라우저에서 사용 → **반응형 필수**
- 세부 계획과 단계별 체크리스트: `docs/PLAN.md`
- API 명세(프론트·백엔드 공통 계약): `docs/API.md`

## 이 세션의 역할: 마스터 세션
메인 세션은 **직접 구현하지 않고 지휘한다.**
1. `docs/PLAN.md`를 읽고 현재 Phase와 남은 작업을 파악한다.
2. 작업을 서브에이전트에게 나눠 맡긴다. 지시할 때는 목표, 범위(건드릴 폴더), 완료 기준, 참고할 문서를 명시한다.
3. 결과를 검토하고, 문제가 있으면 같은 에이전트에게 수정을 지시한다.
4. Phase가 끝나면 사용자에게 확인을 받은 뒤 `docs/PLAN.md` 체크박스를 갱신하고 커밋한다.
5. 되돌리기 어려운 작업(데이터 삭제, 기존 서비스·Caddy 제거, 워크플로의 배포 단계 변경)은 반드시 사용자 승인을 받는다.

작은 수정(오타, 한두 줄)은 마스터가 직접 해도 된다.

### 서브에이전트 (`.claude/agents/`)
| 에이전트 | 담당 | 작업 폴더 |
|---|---|---|
| `ui-builder` | React 화면, 반응형, PWA | `frontend/` |
| `backend-builder` | FastAPI, SQLite, 인증, Claude API 연동 | `backend/` |
| `infra` | Docker Compose, Caddy, GitHub Actions, 배포·백업 스크립트 | `deploy/`, `.github/workflows/`, 루트의 compose 파일 |
| `security-reviewer` | 인증·세션·비밀값 보안 검토 (코드 수정 안 함) | 결과: `docs/reviews/` |
| `qa-reviewer` | 계획 대비 누락, 반응형·동작 점검 (코드 수정 안 함) | 결과: `docs/reviews/` |

### 문서 소유권
- `docs/PLAN.md`: 마스터만 수정
- `docs/API.md`: 마스터가 작성·수정. 빌더들은 읽기만 하고, 변경이 필요하면 결과 보고에 "API 변경 제안"으로 적는다.
- `docs/reviews/`: 리뷰어가 작성, 마스터가 읽고 조치

### 진행 원칙
- **UI 확정(Phase 1) 전에는 백엔드를 시작하지 않는다.** UI 확정 → API.md 확정 → 백엔드/인프라 순서.
- 한 번에 하나의 Phase만 진행한다.
- 인증(Phase 4)이 끝나면 반드시 `security-reviewer`를 돌린다.
- 각 Phase 끝에 `qa-reviewer`로 PLAN.md 대비 누락을 점검한다.

## Git·배포 규칙 (중요)
- `main`에 직접 커밋·push하지 않는다. 작업은 브랜치(`feat/...`, `fix/...`)에서 하고 PR을 만든다.
- PR 병합은 사용자가 한다. 마스터는 PR 설명에 변경 요약, 확인 방법, 관련 Phase를 적는다.
- **운영 서버에 접속하지 않는다.** SSH, scp, 원격 docker 명령 모두 금지. 운영 반영은 `main` 병합 후 GitHub Actions만 한다.
- 서버에서 사람이 직접 실행해야 하는 일(최초 설정, 긴급 복구)은 `deploy/README.md`에 명령과 함께 문서로 남긴다.
- 배포 워크플로(`.github/workflows/deploy.yml`)와 배포 스크립트(`deploy/deploy.sh`)를 바꾸는 PR은 PR 설명 맨 위에 "⚠️ 배포 경로 변경"이라고 표시한다.

## 서버 제약 (중요)
- Oracle Cloud 무료 인스턴스: **1코어 / RAM 1GB (+ 스왑 2GB)**
- 헤드리스 브라우저(Chromium, Playwright, Puppeteer) 사용 금지
- 서버에서 프론트엔드 빌드 금지 → 로컬 또는 GitHub Actions에서 빌드
- 도메인: 이미 발급해 서버를 가리키는 **DuckDNS 서브도메인**(`<이름>.duckdns.org`)을 재사용한다. 기존 Caddy(와 기존 컨테이너)는 종료하고 web 컨테이너의 Caddy가 대체한다.
- HTTPS: web 컨테이너의 Caddy가 Let's Encrypt 인증서를 자동 발급 (HTTP-01, 80/443 포트 사용)
- DuckDNS 토큰은 비밀값이다. 서버에만 두고 저장소·CI·로그에 넣지 않는다.

## 기술 스택
- 백엔드: FastAPI (Python 3.12), SQLite + FTS5 (trigram 토크나이저, 한국어 검색용)
- 프론트: React + Vite + TypeScript, vite-plugin-pwa
- 인증: Argon2 비밀번호 해시, TOTP(pyotp, Google Authenticator), 복구 코드
- AI: Anthropic Claude API (공식 Python SDK), 서버 측에서만 호출
- 배포: Docker Compose (api + web), GitHub Actions → GHCR → SSH 배포 스크립트 (설계: `docs/PLAN.md`의 "CI/CD 설계")

## 폴더 구조
```
frontend/        React 앱
backend/         FastAPI 앱
deploy/          Caddyfile, web 이미지 Dockerfile, 배포·백업 스크립트, README(서버 수동 작업 문서)
.github/workflows/  ci.yml(PR 검사), deploy.yml(main 병합 시 배포)
docs/            PLAN.md, API.md, reviews/
docker-compose.yml
.env.example
```

## 공통 규칙
- 비밀값(API 키, 세션 시크릿)은 `.env`에만 저장하고 커밋하지 않는다. `.env.example`만 커밋한다.
- Claude API 키는 프론트엔드에 절대 노출하지 않는다.
- 인증 토큰은 localStorage에 저장하지 않는다. 서버가 설정하는 HttpOnly + Secure + SameSite 쿠키만 사용한다.
- AI가 추출한 값(제목, 마감일, 메모, 주제)은 자동 저장하지 않고 입력칸에 제안으로만 채운다.
- UI 문구는 한국어로 작성한다.

## 공개 저장소 규칙 (중요)
이 저장소는 **공개(public)**다. 커밋하는 모든 파일과 git 이력은 누구나 볼 수 있다.

### 절대 커밋하지 않는 파일 (`.gitignore`에 등록됨)
- 비밀값: `.env`, `.env.*`(`.env.example` 제외), SSH 키(`id_*`, `*.pem`, `*.key`, 배포 키), `known_hosts`, DuckDNS 토큰(`duckdns/`), `secrets/`
- 데이터: SQLite DB(`*.db`, `*.sqlite*`, `data/`), 백업(`backups/`, `*.bak`), 로그(`logs/`, `*.log`), Caddy 인증서(`caddy_data/`)
- 인증 산출물: TOTP 비밀값·QR 이미지, 복구 코드 파일
- 보안 리뷰 결과: `docs/reviews/security-*.md` (조치 전 취약점 노출 방지, 로컬에만 보관). QA 점검 중 나온 보안 지적도 `qa-*.md`에 쓰지 않고 `security-qa-*.md`로 분리한다
- 개인 설정·로컬 문서: `.claude/settings.local.json`, `CLAUDE.local.md`, `*.local.md`(예: `deploy/README.local.md` — 서버 고유 기록·일회성 작업)

### 파일 내용에도 넣지 않는 값 (코드·문서·주석·테스트·커밋 메시지 모두)
- 실제 DuckDNS 서브도메인, 서버 공인 IP, 서버 사용자 이름·경로 외의 접속 정보 → `<이름>.duckdns.org`, `SITE_DOMAIN` 같은 자리표시자·환경변수로 쓴다
- API 키·토큰·비밀번호의 실제 값 (예시는 `sk-ant-xxxx`처럼 명백한 가짜 값)
- 개인정보: 이메일, 실명, 전화번호, 실제 스크랩 데이터. 목 데이터와 테스트 데이터는 가짜로 만든다
- **보안 약점·운영 이력**: 해결되지 않은 약점, 공략에 쓰일 수 있는 동작(예: 어떤 조건에서 제한이 풀리는지), 키·비밀값 노출 이력, 서버 고유 상태 기록. 이런 내용은 로컬 전용 `docs/reviews/security-*.md` 또는 `deploy/README.local.md`에만 쓴다. 공개 파일에는 설계를 중립적으로 설명하고, 로컬 리뷰 ID(P4-1 등)를 근거로 달지 않는다. PLAN에 넘길 때도 "무엇을 할지"만 쓰고 "무엇이 약한지"는 쓰지 않는다

### 새 파일을 만들 때
- 위 목록에 해당하는 새 종류의 파일이 생기면 `.gitignore`에 추가하고 보고에 적는다.
- Docker 이미지에 `.env`, DB, `.git`이 들어가지 않도록 `.dockerignore`를 둔다 (이미지도 GHCR에서 공개될 수 있다).
- 커밋 전 `git status`와 `git diff --cached`로 올라갈 파일을 확인한다. 비밀값을 실수로 커밋했으면 push 전에 멈추고 사용자에게 알린다 (이미 push됐다면 이력 삭제보다 **키 교체가 우선**).

### GitHub Actions (공개 저장소 주의)
- `pull_request_target` 트리거를 쓰지 않는다 (포크 PR이 시크릿에 접근할 수 있음).
- 시크릿은 `production` Environment에만 두고, 배포 잡만 그 Environment를 사용한다.
