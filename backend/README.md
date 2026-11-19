# backend

FastAPI 앱. 진입점 `app.main:app`, 작업 디렉터리는 이 폴더(`backend/`).

## 로컬 실행
```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
mkdir -p data                       # 기본 DB 경로 ./data/dev.db 의 디렉터리 (자동 생성하지 않음)
ENABLE_API_DOCS=1 .venv/bin/uvicorn app.main:app --reload
curl http://127.0.0.1:8000/api/health   # {"status":"ok"}
```

## 검사 (CI와 동일)
```sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
```

## 환경변수
| 이름 | 기본값 | 설명 |
|---|---|---|
| `DB_PATH` | `./data/dev.db` | SQLite 파일 경로. 상위 디렉터리가 없으면 만들지 않고 `/api/health`가 503 |
| `ENABLE_API_DOCS` | (꺼짐) | `1`이면 `/api/docs`, `/api/redoc`, `/api/openapi.json` 노출. 운영에서는 켜지 않는다 |

`SESSION_SECRET`, `ANTHROPIC_API_KEY`는 아직 사용하지 않는다 (Phase 4, 7).
