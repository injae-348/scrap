# syntax=docker/dockerfile:1
# web 이미지: Caddy + 빌드된 프론트(dist) + 운영 Caddyfile.
# 빌드 컨텍스트는 저장소 루트 (frontend/ 와 deploy/Caddyfile 이 필요). GitHub Actions에서만 빌드한다.
#
#   docker buildx build --platform linux/amd64 -f deploy/web.Dockerfile .
#
# - 프론트는 이 Dockerfile 안의 node 단계에서 빌드한다 (러너에서 빌드한 dist를 COPY하지 않음).
#   이유: 이미지가 커밋 하나로 재현되고(로컬에서도 같은 명령), CI 단계 간 산출물 전달이 필요 없으며,
#   BuildKit 캐시(GHA)로 npm ci 를 건너뛸 수 있다. 서버에서는 이 이미지를 pull 만 한다.
# - node 단계는 --platform=$BUILDPLATFORM: 결과물(dist)은 플랫폼과 무관한 정적 파일이므로
#   서버 아키텍처가 달라도 에뮬레이션 없이 러너에서 바로 빌드한다.
# - 베이스는 정확한 태그 + 다이제스트로 고정. caddy 버전은 Phase 2 bootstrap(deploy/bootstrap)과 같게 둔다.
# - 컨텍스트에서 제외할 파일은 루트 .dockerignore (허용 목록 방식).

# ── build: 프론트 정적 파일 ─────────────────────────
FROM --platform=$BUILDPLATFORM node:22.23.5-trixie-slim@sha256:68c76cfad89921b927eae28ba21407475e29d0ce450afcdbe70c1532db042b64 AS build

WORKDIR /src
ENV npm_config_fund=false \
    npm_config_audit=false \
    npm_config_update_notifier=false

# 의존성 목록이 바뀌지 않으면 이 층은 캐시를 쓴다.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ── runtime: Caddy ─────────────────────────────────
FROM caddy:2.11.4-alpine@sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b

COPY deploy/Caddyfile /etc/caddy/Caddyfile
# 빌드 때 Caddyfile 문법을 확인한다 (adapt 는 설정 변환만 하고 인증서 발급·저장소 쓰기를 하지 않는다).
RUN SITE_DOMAIN=example.invalid caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null

COPY --from=build /src/dist /srv

# caddy 공식 이미지의 기본 CMD(caddy run --config /etc/caddy/Caddyfile --adapter caddyfile)를 그대로 쓴다.
# 인증서·ACME 계정(/data)과 자동 설정(/config)은 docker-compose.yml 에서 서버 폴더로 붙인다.
