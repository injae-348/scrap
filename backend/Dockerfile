# api 이미지 (FastAPI). 빌드 컨텍스트는 backend/ — GitHub Actions에서만 빌드한다 (서버에서 빌드 금지).
#
#   docker buildx build --platform linux/amd64 -f backend/Dockerfile backend
#
# - 베이스는 정확한 태그 + 다이제스트로 고정한다 (같은 태그가 다시 올라와도 결과가 바뀌지 않게).
#   올릴 때는 두 값을 함께 바꾼다: https://hub.docker.com/_/python
# - 멀티스테이지: build 단계에서 가상환경(/opt/venv)에 의존성을 설치하고, 런타임에는 그 venv만 복사한다.
#   pip 캐시·빌드 산출물이 런타임 이미지에 남지 않는다. (C 확장을 소스에서 빌드해야 하는 패키지가 생기면
#   build 단계에만 build-essential 을 추가한다 — 런타임에는 넣지 않는다.)
# - 실행 사용자 UID/GID 10001 (non-root). 서버 /opt/scrap-app/data 의 소유자와 같아야 SQLite를 열 수 있다
#   (deploy/README.md 3-2). 바꾸면 서버 data/ 소유자도 함께 바꿔야 한다.
# - 앱 코드는 app/ 패키지만 복사한다. .env·DB·테스트는 backend/.dockerignore 와 이 COPY 범위로 이중으로 막는다.

ARG PYTHON_IMAGE=python:3.12.16-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

# ── build: 의존성 설치 ───────────────────────────────
FROM ${PYTHON_IMAGE} AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ── runtime ─────────────────────────────────────────
FROM ${PYTHON_IMAGE} AS runtime

# HOME=/tmp: 루트 파일시스템이 읽기 전용(compose read_only)이므로 라이브러리 캐시 등은 tmpfs(/tmp)로 보낸다.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    HOME=/tmp

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent \
      --shell /usr/sbin/nologin app

COPY --from=build /opt/venv /opt/venv

WORKDIR /app
# 코드는 root 소유(읽기 전용)로 두고, 실행 사용자는 /data(볼륨)와 /tmp에만 쓴다.
COPY app ./app
# 실행 중에는 .pyc를 쓰지 않으므로(PYTHONDONTWRITEBYTECODE) 빌드 때 미리 만들어 시작 시간을 줄인다.
RUN python -m compileall -q /app/app

USER 10001:10001
EXPOSE 8000

# 기본 실행: 1 worker (1코어/1GB 서버). 프록시 헤더 신뢰 범위(--forwarded-allow-ips)는
# 네트워크 구성을 아는 docker-compose.yml 의 command 에서 지정한다 (기본값은 127.0.0.1만 신뢰).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-server-header"]
