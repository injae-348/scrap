# 개발 계획

## 기능 요구사항
1. **출처(source)**: 유튜브 / X / 일반사이트 / 당근 / 커뮤니티 등. 스크랩당 1개. URL 도메인으로 자동 판별하고 수정 가능.
2. **주제(topic)**: claude, security, docker 등. 스크랩당 여러 개. 사용자가 직접 추가/관리.
3. **좋아요**: 좋아요 누른 스크랩만 따로 모아보기.
4. **제목 + 메모**: 메모는 장문(마크다운) 가능.
5. **마감일(due_date)**: 선택 필드. 직접 입력 또는 AI로 채우기.
6. **AI로 채우기**: URL 본문을 가져와 Claude가 제목/마감일/요약 메모/추천 주제를 JSON으로 제안 → 입력칸에 채워 넣기만 함.
   - 본문을 가져오지 못하는 사이트용으로 "본문 붙여넣기" 입력칸 제공.
   - 본문 추출은 브라우저 없이 (제목 미리보기와 같은 안전한 가져오기 모듈 + trafilatura).
7. **AI 검색**: "이런 공모전 찾아줘" → Claude가 `search_scraps` 도구를 여러 번 호출(동의어 포함) → 관련 스크랩을 이유와 함께 반환.
8. **인증**
   - 사용자가 0명일 때만 가입 가능. 가입 후 가입 API 영구 비활성화.
   - TOTP 2차 인증 (QR 등록, 6자리 확인), 복구 코드 10개.
   - 무한 로그인: 서버 세션 테이블 + 만료 없는(또는 슬라이딩 갱신) HttpOnly 쿠키.
   - 로그아웃, "모든 기기 로그아웃"(현재 기기 포함), 로그인된 기기 목록.
   - 로그인 실패 횟수 제한.
   - 최초 가입 토큰(`SETUP_TOKEN`): 서버 `.env`에만 두고, 이 값을 아는 사람만 최초 가입 가능. 가입 후 삭제.
9. **저장 동선**: 링크 복사 → PWA 실행 → "링크 붙여넣기" 버튼(클립보드 읽기) → 저장. (iOS PWA는 공유 시트 미지원)

## 데이터 모델
```
users          id, username, password_hash, totp_secret, totp_last_step, created_at
recovery_codes id, user_id, code_hash, used_at
sessions       id, user_id, token_hash, user_agent, created_at, last_seen_at
sources        id, name, domain_patterns, sort_order
topics         id, name, sort_order
scraps         id, url, title, memo, source_id, liked, due_date, created_at, updated_at
scrap_topics   scrap_id, topic_id
scraps_fts     FTS5(title, memo, url, topics) tokenize='trigram'
```

## 반응형 레이아웃
- **모바일**: 하단 탭바(전체 / 좋아요 / AI 검색 / 설정) + 떠 있는 "+" 저장 버튼
- **데스크톱**: 왼쪽 사이드바(출처, 주제, 좋아요, 마감 임박) + 가운데 목록 + 오른쪽 상세/편집 패널

## 화면 목록
1. 최초 가입 + 2차 인증 등록 (QR, 복구 코드)
2. 로그인 (비밀번호 → 6자리 코드)
3. 목록 (출처 탭, 주제 필터, 정렬: 최신순/마감순, 마감 임박 표시)
4. 저장/수정 (링크 붙여넣기, AI로 채우기, 본문 붙여넣기, 주제 선택, 메모, 마감일)
5. 상세 보기
6. 좋아요 모아보기
7. AI 검색 (질문 입력 → 결과 카드)
8. 설정 (주제/출처 관리, 로그인 기기, 로그아웃, 2차 인증 재설정)

## 단계별 진행

### Phase 0. GitHub 저장소
- [x] GitHub **공개** 저장소 생성, 첫 커밋 push (규칙: `CLAUDE.md`의 "공개 저장소 규칙")
- [x] 커밋 이메일을 GitHub noreply 주소로 설정 (개인 이메일 노출 방지)
- [x] 저장소 설정: Secret scanning + Push protection 켜기, 포크 PR 워크플로 실행 시 승인 필요
- [x] `main` 브랜치 보호: 직접 push 금지, PR 필수, 삭제·강제 push 금지 (ruleset `rule`, 필요 승인 0) — CI 필수 검사는 Phase 1에서 추가
- [x] 작업 방식: 기능마다 브랜치 → PR → CI 통과 → 사용자 확인 후 병합

### Phase 1. UI 프로토타입
- [x] React + Vite + TS 프로젝트 생성, 목(mock) 데이터로 전체 화면 구현
- [x] 모바일(375px)과 데스크톱(1280px)에서 모두 확인 (브라우저 에뮬레이션. 실기기 아이폰은 Phase 6)
- [x] 디자인 확정 후 다음 단계로 (2026-11-19 확정, API.md v1 확정, QA: `docs/reviews/qa-1-20261119.md`)
- [x] CI(검사만): PR마다 프론트 린트·타입체크·빌드 (`.github/workflows/ci.yml`)
- [x] CI가 한 번 돈 뒤 ruleset `rule`에 "Require status checks to pass"로 CI 잡 `frontend` 추가 (사용자가 GitHub에서 설정 — PR #2 병합 후)

### Phase 2. 서버 준비
> 서버 아키텍처는 x86_64 → 이미지 `linux/amd64`. 절차: `deploy/README.md` (서버 고유 기록은 로컬 `deploy/README.local.md`)
- [x] 서버 아키텍처 확인 (`uname -m` = x86_64)
- [x] 스왑 2GB, Docker 설치, OCI 보안 목록·iptables 80/443 개방 (기존에 완료)
- [x] DuckDNS 서브도메인 발급·서버 IP 연결 (기존 도메인 재사용)
- [x] 서버 현황 확인 결과 공유 (README 1단계)
- [x] 기존 컨테이너·Caddy 중지 (80/443 비우기) — 기존 앱 데이터 불필요로 백업 생략
- [x] DuckDNS IP 자동 갱신 cron (토큰 파일 600)
- [x] 배포 전용 사용자(`deploy`)와 배포 전용 SSH 키 등록 (아래 "CI/CD 설계" 참고)
- [x] Docker Compose 구성 (api + web), 앱 디렉터리 `/opt/scrap-app` (서버 폴더 bind mount)
- [x] 서버의 `.env`는 서버에서 직접 작성 (저장소·CI에 넣지 않음)
- [x] 첫 확인: 임시 페이지(bootstrap)로 새 web Caddy가 `https://<이름>.duckdns.org` 인증서 발급 — 인증서 디렉터리(`/data`)는 볼륨으로 유지
- [x] 기존 이미지·컨테이너·볼륨·폴더·crontab 정리 (2026-11-19 완료)
- [x] 기존 앱의 배포 설정 정리 (2026-11-20 확인)

### Phase 3. CI/CD 파이프라인
> 결정 사항 (2026-11-19 사용자 확정, 근거: Phase 2 QA `docs/reviews/qa-2-20261119.md`):
> 1. **서버 파일(compose, `deploy.sh`)은 사람이 수동 갱신.** 배포 스크립트는 이미지 태그만 바꾼다. 서버 파일을 바꾸는 PR은 설명에 "🖐 서버 파일 갱신 필요"를 표시하고, 병합 후 사용자가 `deploy/README.md`의 갱신 절차(`sudo install`)를 실행한 뒤 배포를 승인한다.
> 2. **api 컨테이너 UID = 10001 고정** (`backend/Dockerfile`, 서버 `data/` 소유자와 일치).
> 3. **배포 직전 DB 백업은 api 컨테이너 안에서** (Python `sqlite3` backup API) 실행하고 결과를 호스트 `backups/`로 꺼낸다. DB나 컨테이너가 없으면(첫 배포) 건너뛴다.
> 4. **롤백 상태는 `/opt/scrap-app/state/`** (deploy 소유)에 현재·직전 SHA를 기록. `.env`의 `IMAGE_TAG`는 건드리지 않는다.
> 5. **compose 고정 네트워크(서브넷 고정) + web 고정 IP**, uvicorn `--proxy-headers --forwarded-allow-ips=<web IP>`로 web만 신뢰.
> 6. **배포 후 헬스체크는 실제 도메인 HTTPS** `https://<도메인>/api/health` (Caddy·인증서·프록시까지 검증). 실패 시 직전 SHA로 롤백.
> 7. **GHCR 이미지 공개.** 서버 `docker login` 불필요. 첫 push 후 사용자가 패키지 2개를 공개로 전환. 이미지에 비밀값이 들어가지 않게 `.dockerignore`로 막는다.
- [x] CI 확장: 백엔드 pytest + 프론트 빌드를 PR마다 실행 (`ci.yml`: frontend·backend·images, 필수 검사 3개 — 2026-11-19 사용자 설정)
- [x] CD: `main` 병합 시 이미지 빌드 → GHCR push → 서버 배포 (`.github/workflows/deploy.yml`, 패키지 `scrap-api`·`scrap-web` 공개)
- [x] GitHub Environment `production` + 배포 전 수동 승인(본인, 관리자 우회 끔, main만, Environment 시크릿 4개)
- [x] 배포 후 헬스체크, 실패 시 직전 버전으로 롤백 (`deploy.sh`, 수동 복구 `rollback.sh` — 롤백 경로는 하네스로만 검증, 운영에서는 아직 미발생)
- [x] 빈 앱(헬스체크 엔드포인트만)으로 파이프라인 끝까지 한 번 성공시키기 (2026-11-19 PR #5 병합 → 승인 → 배포 성공, 서버·외부 헬스체크 통과, README 12-4 확인 전부 통과. QA: `docs/reviews/qa-3-20261119.md`)

### Phase 4. 인증
> 결정 사항 (2026-11-20 사용자 확정): 세션은 180일 미사용 시 만료(쿠키 400일, 접속 시 갱신). 최초 가입은 `SETUP_TOKEN`으로 보호(도메인은 인증서 공개 기록으로 이미 알려져 있음). 프론트 연동은 Phase 6. 서버 수동 점검(`SESSION_SECRET`·`SETUP_TOKEN`)과 최초 가입 절차는 README에 쓰지 않고 마스터가 세션에서 안내한다. 리뷰: `docs/reviews/qa-4-20261120.md` (보안 리뷰는 로컬 전용).
- [x] 최초 가입, TOTP 등록, 복구 코드
- [x] 로그인(비밀번호 → TOTP), 세션 쿠키, 로그아웃, 전체 로그아웃, 기기 목록
- [x] 로그인 실패 제한 (공통 요청 제한 미들웨어로 만들어 인증 없는 `/api/health`에도 적용 검토)
- [x] `SESSION_SECRET`이 `.env.example` 자리표시자이거나 너무 짧으면 앱 기동 거부
- [x] 최초 가입 토큰(`SETUP_TOKEN`), 운영 설정 가드(운영에서 개발용 설정이면 기동 거부)
- [x] security-reviewer 검토 및 조치 (중간 이상 지적은 Phase 4에서 수정, 나머지는 Phase 5~8로 이동)
- [x] 운영 배포 (2026-11-20 PR #7 병합 → 승인 → 배포 성공, 외부 health·`/api/auth/status` 확인. 최초 가입은 Phase 6 가입 화면에서 진행)

### Phase 5. 스크랩 API
> 결정 사항 (2026-11-20): 세부 규칙은 `docs/API.md` v1.3. 기본 출처 5개(유튜브·X·일반사이트·당근·커뮤니티), 같은 URL 중복 저장 허용, 목록 기본 30개(최대 100), 제목 미리보기는 포트 80·443만·분당 20회, URL의 사용자 정보(`user:pass@`)는 거부. 요청 본문 상한은 앱 1MB(인증 불필요 경로 16KB) + Caddy. 리뷰: `docs/reviews/qa-5-20261120.md` (보안 리뷰는 로컬 전용).
- [x] 스크랩 CRUD, 출처 자동 판별, 주제 관리, 좋아요, 마감일
- [x] 제목 자동 채움 (og:title, 유튜브 oEmbed; 실패 시 빈칸)
- [x] FTS5 trigram 검색 (1~2글자 단어는 부분 문자열)
- [x] (Phase 4에서 넘김) 착수 조건: 새 라우터는 인증 기본 적용 + `/auth/*` 외 모든 `/api/*`가 미인증 시 401인지 전수 테스트 (기본 거부 상위 라우터 + 기동 시 전수 검사, 본문 읽기 전 세션 확인)
- [x] (Phase 4에서 넘김) URL을 가져오는 기능은 http/https 스킴만 허용 (제목 자동 채움)
- [x] (Phase 4에서 넘김) 마이그레이션은 추가 위주로 작성 (구 이미지로 롤백 가능하게), 하위 의존성 고정·취약점 검사(pip-audit) 도입 (uv 해시 고정, CI `backend` 잡에 pip-audit)
- [x] 운영 배포 (2026-11-20 PR #9 병합 → 승인 → 배포 성공, 외부 health·미인증 401·본문 상한 확인. 스크랩 API 실사용 확인은 Phase 6 가입 후)

### Phase 6. 프론트 연동 + PWA
> 결정 사항 (2026-11-21): 목록 응답은 메모 대신 `memo_preview`(앞 300자), 전문은 상세에서만 (`docs/API.md` v1.4). 목 데이터는 삭제하고 실제 API만 쓴다. 서비스워커는 새 버전을 자동 적용하지 않고 "새로고침" 안내로 묻는다(작성 중이면 확인). 리뷰: `docs/reviews/qa-6-20261121.md` (보안 리뷰는 로컬 전용).
- [x] Phase 1 QA에서 넘긴 것: 개발용 섹션·"목 모드" 문구 제거, 401/`/auth/status` 오류 처리, 작성 중 이탈 경고, 사이드바 주제 다중 선택 (`docs/reviews/qa-1-20261119.md`)
- [x] 목 데이터를 실제 API로 교체
- [x] manifest, 아이콘, 서비스워커 → 아이폰 홈 화면 추가 테스트 (2026-11-21 실기기 통과)
- [x] 클립보드 붙여넣기 동선 테스트 (iOS Safari, 2026-11-21 실기기 통과)
- [x] (Phase 4에서 넘김) 인증 화면 연동: 가입 화면 `setup_token` 입력칸, `error.code`별 화면 처리(401은 `unauthorized`일 때만 로그인 화면), 복구 코드 한 번만 표시, 로그인 입력칸 iOS 속성, 기기 목록 `last_seen_at`, 전체 로그아웃 후 로그인 화면 (`docs/reviews/qa-4-20261120.md` 5절)
- [x] (Phase 4에서 넘김) 개발 설정: Vite `/api` 프록시 + `COOKIE_SECURE=0`·`ALLOWED_ORIGINS`, 서비스워커 캐시에서 `/api/*` 제외
- [x] (Phase 4에서 넘김) `VITE_` 접두사 변수는 공개 값 전용(번들·공개 이미지에 들어감) 규칙 문서화, CI에서 빌드 결과물에 비밀값 패턴이 없는지 검사
- [x] (Phase 5에서 넘김, 착수 조건) 메모 마크다운은 원시 HTML을 끄거나 무해화해서 렌더링, 링크는 http/https만 `rel="noopener noreferrer"`, 제목·메모에 `dangerouslySetInnerHTML` 금지 + 렌더링 단위 테스트
- [x] (Phase 5에서 넘김) 목 데이터·오류 코드·커서를 서버 기준으로 정리 (`docs/reviews/qa-5-20261120.md`), PATCH에는 바뀐 필드만, 필터가 바뀌면 커서 버리기, 미리보기 로딩은 입력을 막지 않게
- [x] (Phase 5에서 넘김, API 결정) 목록 응답의 메모를 앞부분만 줄지 결정 (상세에서 전문) → `memo_preview` 300자 (API.md v1.4)
- [x] 운영 배포 (2026-11-21 PR #11 병합 → 승인 → 배포 성공, 외부 health·PWA 파일 헤더 확인, 최초 가입 완료, 아이폰 홈 화면 앱 확인)

### Phase 7. AI 기능
- [ ] AI로 채우기 (본문 추출 → Claude 구조화 출력 → 제안 표시)
- [ ] AI 검색 (도구 호출 루프, 결과 카드)
- [ ] (Phase 4에서 넘김) 본문 추출은 http/https 스킴만 허용
- [ ] (Phase 6에서 넘김) `/ai/*` 404를 "준비 중"으로 바꾸는 프론트 처리 제거, AI 오류 코드 정리, `/ai/search` 결과의 `scrap` 형식(전문 또는 `ScrapListItem`) 결정
- [ ] (Phase 6에서 넘김) 메모 속 외부 링크 옆에 실제 호스트 표시 (AI가 제안한 메모 대비)
- [ ] (Phase 5에서 넘김, 착수 조건) 본문 추출은 제목 미리보기의 안전한 가져오기 구현을 공통 모듈로 분리해 재사용 (다른 HTTP 클라이언트 사용 금지), HTML 파싱 입력 크기 상한과 파싱 전용 동시 실행 제한
- [ ] `/ai/*` 전용 요청 제한: 공통 제한보다 낮은 분당 상한과 하루 호출 상한 (넘으면 429 `too_many_requests`)
- [ ] `ANTHROPIC_API_KEY` 설정 검사: 없거나 `.env.example` 자리표시자 그대로면 앱은 정상 기동하고 AI 기능만 "사용 불가"로 응답. 키 값은 설정 객체 출력·로그·오류 응답에 넣지 않는다

### Phase 8. 운영
- [ ] SQLite 자동 백업 (cron + `sqlite3 .backup`, 외부로 복사), 배포 직전 자동 백업
- [ ] 운영 절차 문서화 (`deploy/README.md`: 수동 롤백, 백업 복원, 비밀값 교체)
- [ ] CI 배포 키 정기 교체 절차, GHCR 옛 이미지 보존 기간 정책
- [ ] (Phase 4에서 넘김) 외부로 복사하는 백업은 암호화 필수 (DB에 인증 정보 포함), WAL 모드에 맞춘 백업·복원
- [ ] (Phase 4에서 넘김) 계정 복구 절차 (인증 앱과 복구 코드를 모두 잃은 경우)
- [ ] (Phase 4에서 넘김) 운영 문서에 비밀값을 화면에 펼치는 진단 명령 금지 목록, 컨테이너 로그 크기 상한, (선택) compose `secrets:`로 비밀값 전달
- [ ] (Phase 4에서 넘김) infra 규칙: 비밀값을 `--build-arg`·이미지 `ENV`로 넣지 않는다 (공개 이미지 `docker history`로 보임)
- [ ] (Phase 5에서 넘김) 다음 compose 갱신 때: 컨테이너 로그 크기 상한, api 기동 명령에 `--loop=uvloop --http=httptools` 명시
- [ ] (Phase 6에서 넘김) PWA 갱신: 배포마다 index.html에 빌드 식별자를 넣어 갱신 안내가 항상 뜨게 하기, 서비스워커 해제 절차를 운영 문서에 두기, (선택) 최소 프론트 버전 확인
- [ ] (Phase 6에서 넘김) CI 보강: 프론트 의존성 취약점 검사(npm audit), 빌드 결과물 비밀값 검사를 이미지 빌드 단계에서도 실행, `VITE_` 변수 허용 목록 검사, (선택) COOP·CORP 헤더
- [ ] (Phase 5에서 넘김) 접근 로그에서 쿼리 문자열(검색어·커서) 빼기, pip-audit 정기 실행(예: 주 1회 예약 워크플로), `scraps_fts` 무결성 확인·재구성 절차 문서화

## 도메인 (DuckDNS)

### 발급
1. duckdns.org에서 로그인 (GitHub 계정 등) → 원하는 서브도메인 추가
2. 서브도메인의 IP를 오라클 서버의 **공인 IP**로 설정
3. 페이지 상단의 **토큰**을 확인 (비밀값, 노출 금지)

### IP 자동 갱신
- 오라클 공인 IP가 바뀌는 경우(인스턴스 재생성 등)에 대비해 서버에서 5분마다 DuckDNS에 현재 IP를 알려 준다.
- 토큰은 `/opt/scrap-app/duckdns/token` 파일(권한 600)에 두고, 스크립트가 파일에서 읽는다. crontab이나 스크립트 본문에 토큰을 직접 쓰지 않는다.
  ```
  */5 * * * * /opt/scrap-app/deploy/duckdns-update.sh >> /opt/scrap-app/logs/duckdns.log 2>&1
  ```

### HTTPS
- Caddyfile의 사이트 주소를 `<이름>.duckdns.org`로 두면 Caddy가 Let's Encrypt 인증서를 자동으로 받고 갱신한다.
- 조건: DNS가 서버 IP를 가리키고, OCI 보안 목록과 서버 iptables에서 **80, 443 포트가 열려 있을 것** (80은 인증서 발급 확인용).
- 인증서 저장 경로는 볼륨으로 유지한다. 재배포 때마다 새로 받으면 Let's Encrypt 발급 횟수 제한에 걸릴 수 있다.
- 도메인 이름은 Caddyfile에 하드코딩하지 않고 환경변수(`SITE_DOMAIN`)로 받는다.

## CI/CD 설계

### 전체 흐름
```
기능 브랜치 push → PR
   └─ ci.yml: 백엔드 pytest, 프론트 린트·타입체크·빌드   (검사만, 배포 없음)
main 병합
   └─ deploy.yml
        1. 테스트 재실행
        2. 이미지 2개 빌드 (서버 아키텍처용) → GHCR push, 태그 = 커밋 SHA
             - api : FastAPI 백엔드
             - web : Caddy + 빌드된 프론트 dist + Caddyfile
        3. [수동 승인] GitHub Environment "production"
        4. SSH로 서버 접속 → 배포 스크립트 실행 (SHA만 전달)
             - DB 백업
             - 새 이미지 pull → docker compose up -d
             - 헬스체크 (/api/health) 실패 시 직전 SHA 태그로 롤백
```

### 원칙
- **빌드는 전부 GitHub Actions에서.** 서버는 이미지 pull과 재시작만 한다 (1GB 서버 보호).
- **서버 아키텍처에 맞게 빌드.** aarch64면 buildx로 `linux/arm64` 이미지를 만든다.
- **배포는 CI만 한다.** 사람이든 AI든 서버에서 직접 코드를 고치거나 수동 배포하지 않는다 (긴급 롤백 제외).
- **프론트도 이미지로 배포.** 파일을 서버에 복사(scp/rsync)하지 않으므로 배포 키를 스크립트 실행 하나로 묶을 수 있고, 롤백도 태그 하나로 프론트·백엔드가 함께 돌아간다.
- **이미지 태그는 커밋 SHA.** `latest`만 쓰지 않고, 직전 태그를 서버에 기록해 롤백에 쓴다.

### 배포용 SSH 접근 제한
- 서버에 배포 전용 사용자 `deploy`를 만들고, CI 전용 SSH 키를 따로 발급한다 (개인 키 재사용 금지).
- `authorized_keys`에 강제 명령을 걸어 **이 키로는 배포 스크립트만 실행**되게 한다.
  ```
  command="/opt/scrap-app/deploy/deploy.sh",no-port-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA... ci-deploy
  ```
- 배포 대상 커밋 SHA는 SSH 명령 인자로 넘기고(`SSH_ORIGINAL_COMMAND`), 스크립트는 SHA 형식(16진수 40자)만 허용한다.
- OCI 보안 목록에서 22번 포트를 열어 두되 비밀번호 로그인은 끈다.

### GitHub `production` Environment 시크릿
(저장소 시크릿이 아니라 Environment 시크릿 — 승인 전에는 배포 잡도 읽을 수 없다)

| 이름 | 내용 |
|---|---|
| `DEPLOY_HOST` | `<이름>.duckdns.org` (IP 대신 도메인 — 배포 후 외부 헬스체크에도 쓰고, 공개 Actions 로그에서 `***`로 가려진다) |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_SSH_KEY` | CI 전용 개인 키 |
| `DEPLOY_KNOWN_HOSTS` | `<도메인> ssh-ed25519 AAAA...` 한 줄 — 서버에서 직접 읽은 호스트 키 (`deploy/README.md` 5-4, 중간자 공격 방지) |

- GHCR push는 워크플로의 기본 `GITHUB_TOKEN`(`packages: write`)을 사용한다.
- GHCR 패키지(`scrap-api`, `scrap-web`)는 **공개**라 서버는 로그인 없이 pull한다 (Phase 3 결정 7). 이미지에 비밀값이 들어가지 않게 `.dockerignore`로 막는다.
- `ANTHROPIC_API_KEY` 등 앱 비밀값은 GitHub에 넣지 않고 서버 `.env`에만 둔다.

### 수동 승인
- GitHub Environment `production`에 본인을 필수 승인자로 지정한다. 병합 후 Actions 화면(모바일 GitHub 앱 포함)에서 승인해야 배포된다.
- 익숙해지면 승인을 끄고 완전 자동으로 바꿀 수 있다.
