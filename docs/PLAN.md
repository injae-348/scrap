# 개발 계획

## 기능 요구사항
1. **출처(source)**: 유튜브 / X / 일반사이트 / 당근 / 커뮤니티 등. 스크랩당 1개. URL 도메인으로 자동 판별하고 수정 가능.
2. **주제(topic)**: claude, security, docker 등. 스크랩당 여러 개. 사용자가 직접 추가/관리.
3. **좋아요**: 좋아요 누른 스크랩만 따로 모아보기.
4. **제목 + 메모**: 메모는 장문(마크다운) 가능.
5. **마감일(due_date)**: 선택 필드. 직접 입력 또는 AI로 채우기.
6. **AI로 채우기**: URL 본문을 가져와 Claude가 제목/마감일/요약 메모/추천 주제를 JSON으로 제안 → 입력칸에 채워 넣기만 함.
   - 본문을 가져오지 못하는 사이트용으로 "본문 붙여넣기" 입력칸 제공.
   - 본문 추출은 브라우저 없이 (httpx + trafilatura).
7. **AI 검색**: "이런 공모전 찾아줘" → Claude가 `search_scraps` 도구를 여러 번 호출(동의어 포함) → 관련 스크랩을 이유와 함께 반환.
8. **인증**
   - 사용자가 0명일 때만 가입 가능. 가입 후 가입 API 영구 비활성화.
   - TOTP 2차 인증 (QR 등록, 6자리 확인), 복구 코드 10개.
   - 무한 로그인: 서버 세션 테이블 + 만료 없는(또는 슬라이딩 갱신) HttpOnly 쿠키.
   - 로그아웃, "다른 기기 모두 로그아웃", 로그인된 기기 목록.
   - 로그인 실패 횟수 제한.
9. **저장 동선**: 링크 복사 → PWA 실행 → "링크 붙여넣기" 버튼(클립보드 읽기) → 저장. (iOS PWA는 공유 시트 미지원)

## 데이터 모델
```
users          id, username, password_hash, totp_secret, created_at
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
- [ ] React + Vite + TS 프로젝트 생성, 목(mock) 데이터로 전체 화면 구현
- [ ] 모바일(375px)과 데스크톱(1280px)에서 모두 확인
- [ ] 디자인 확정 후 다음 단계로
- [ ] CI(검사만): PR마다 프론트 린트·타입체크·빌드 (`.github/workflows/ci.yml`)
- [ ] CI가 한 번 돈 뒤 ruleset `rule`에 "Require status checks to pass"로 CI 잡 추가 (사용자가 GitHub에서 설정)

### Phase 2. 서버 준비
- [ ] 서버 아키텍처 확인 (`uname -m`: x86_64 / aarch64) → Docker 이미지 플랫폼 결정
- [ ] 기존 서비스 백업 후 제거 (기존 Caddy 포함 — 설정 파일만 백업해 두고 중지·삭제해서 80/443 포트 비우기)
- [ ] Docker 설치
- [ ] **DuckDNS 설정** (아래 "도메인 (DuckDNS)" 참고): 서브도메인 발급 → 서버 공인 IP 연결 → IP 자동 갱신 cron
- [ ] 배포 전용 사용자(`deploy`)와 배포 전용 SSH 키 생성 (아래 "CI/CD 설계" 참고)
- [ ] Docker Compose 구성 (api + web), 앱 디렉터리 `/opt/scrap-app`
- [ ] web 컨테이너(Caddy + 프론트 + `/api` 리버스 프록시)로 DuckDNS 도메인 HTTPS 발급 확인 — 인증서 저장 디렉터리(`/data`)는 볼륨으로 유지
- [ ] 서버의 `.env`는 서버에서 직접 작성 (저장소·CI에 넣지 않음)
- [ ] 첫 확인: 임시 정적 페이지로 `https://<이름>.duckdns.org` 접속 성공

### Phase 3. CI/CD 파이프라인
- [ ] CI 확장: 백엔드 pytest + 프론트 빌드를 PR마다 실행
- [ ] CD: `main` 병합 시 이미지 빌드 → GHCR push → 서버 배포 (`.github/workflows/deploy.yml`)
- [ ] GitHub Environment `production` + 배포 전 수동 승인(본인)
- [ ] 배포 후 헬스체크, 실패 시 직전 버전으로 롤백
- [ ] 빈 앱(헬스체크 엔드포인트만)으로 파이프라인 끝까지 한 번 성공시키기

### Phase 4. 인증
- [ ] 최초 가입, TOTP 등록, 복구 코드
- [ ] 로그인(비밀번호 → TOTP), 세션 쿠키, 로그아웃, 전체 로그아웃, 기기 목록
- [ ] 로그인 실패 제한
- [ ] security-reviewer 검토 및 조치

### Phase 5. 스크랩 API
- [ ] 스크랩 CRUD, 출처 자동 판별, 주제 관리, 좋아요, 마감일
- [ ] 제목 자동 채움 (og:title, 유튜브 oEmbed; 실패 시 빈칸)
- [ ] FTS5 trigram 검색

### Phase 6. 프론트 연동 + PWA
- [ ] 목 데이터를 실제 API로 교체
- [ ] manifest, 아이콘, 서비스워커 → 아이폰 홈 화면 추가 테스트
- [ ] 클립보드 붙여넣기 동선 테스트 (iOS Safari)

### Phase 7. AI 기능
- [ ] AI로 채우기 (본문 추출 → Claude 구조화 출력 → 제안 표시)
- [ ] AI 검색 (도구 호출 루프, 결과 카드)

### Phase 8. 운영
- [ ] SQLite 자동 백업 (cron + `sqlite3 .backup`, 외부로 복사), 배포 직전 자동 백업
- [ ] 운영 절차 문서화 (`deploy/README.md`: 수동 롤백, 백업 복원, 비밀값 교체)

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

### GitHub Secrets
| 이름 | 내용 |
|---|---|
| `DEPLOY_HOST` | `<이름>.duckdns.org` 또는 서버 IP |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_SSH_KEY` | CI 전용 개인 키 |
| `DEPLOY_KNOWN_HOSTS` | 서버 호스트 키 (`ssh-keyscan` 결과) — 중간자 공격 방지 |

- GHCR push는 워크플로의 기본 `GITHUB_TOKEN`(`packages: write`)을 사용한다.
- 서버의 GHCR pull은 **읽기 전용** 토큰(`read:packages`)으로 서버에서 한 번 `docker login` 해 둔다.
- `ANTHROPIC_API_KEY` 등 앱 비밀값은 GitHub에 넣지 않고 서버 `.env`에만 둔다.

### 수동 승인
- GitHub Environment `production`에 본인을 필수 승인자로 지정한다. 병합 후 Actions 화면(모바일 GitHub 앱 포함)에서 승인해야 배포된다.
- 익숙해지면 승인을 끄고 완전 자동으로 바꿀 수 있다.
