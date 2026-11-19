"""환경변수 기반 설정.

비밀값(`SESSION_SECRET`, `ANTHROPIC_API_KEY`)은 아직 쓰지 않으므로 여기서 읽지 않는다.
앱은 비밀값 없이도 떠야 한다 (Phase 3).
"""

import os
from dataclasses import dataclass

# 로컬 개발용 기본 경로 (작업 디렉터리 backend/ 기준). 운영에서는 compose가 DB_PATH를 지정한다.
DEFAULT_DB_PATH = "./data/dev.db"

_TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_path: str
    enable_api_docs: bool


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


def load_settings() -> Settings:
    db_path = os.environ.get("DB_PATH", "").strip() or DEFAULT_DB_PATH
    return Settings(
        db_path=db_path,
        # OpenAPI 문서(/api/docs, /api/redoc, /api/openapi.json)는 기본 비활성화. 로컬에서만 켠다.
        enable_api_docs=_env_bool("ENABLE_API_DOCS"),
    )
