"""보조 기능 `/api/meta` — 제목 미리보기 (docs/API.md v1.3 "제목 미리보기 `POST /meta/preview`").

세션 필수 상위 라우터(app/routing.py) 아래에 붙는다 → 로그인한 사용자만 서버가 외부 주소를 가져오게
할 수 있다. 가져오기 자체의 규칙은 app/preview.py.

- IP별 분당 20회 상한을 따로 둔다 (공통 상한보다 낮음). AI로 채우기의 페이지 가져오기와 합산한다
  (`app.state.fetch_limiter`).
  넘으면 429 `too_many_requests` + `Retry-After`.
- DB 연결은 출처 판별 직전에 열고 바로 닫는다
  (최대 5초 걸리는 가져오기 동안 연결을 들고 있지 않는다).
"""

from fastapi import APIRouter, Request
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from app.db import Database, DatabaseUnavailableError
from app.errors import ApiError
from app.preview import PreviewFetcher
from app.ratelimit import RequestRateLimiter, client_key
from app.sources import detect_source_id
from app.validation import StrictBody, validate_url

router = APIRouter(prefix="/meta")

PREVIEW_REQUESTS_PER_MINUTE = 20


class PreviewBody(StrictBody):
    url: str = Field(max_length=100_000)


def _detect_source(database: Database, url: str) -> int:
    try:
        conn = database.connect()
    except DatabaseUnavailableError as exc:
        raise ApiError(503, "db_unavailable", "데이터베이스에 연결할 수 없습니다.") from exc
    try:
        return detect_source_id(conn, url)
    finally:
        conn.close()


@router.post("/preview")
async def preview(body: PreviewBody, request: Request) -> dict[str, object]:
    limiter: RequestRateLimiter = request.app.state.fetch_limiter
    retry_after = limiter.hit(client_key(request.client.host if request.client else None))
    if retry_after is not None:
        raise ApiError(
            429,
            "too_many_requests",
            "제목 미리보기 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
            headers={"Retry-After": str(retry_after)},
        )
    url = validate_url(body.url)
    source_id = await run_in_threadpool(_detect_source, request.app.state.db, url)
    fetcher: PreviewFetcher = request.app.state.preview_fetcher
    title = await fetcher.fetch_title(url)
    return {"title": title, "source_id": source_id}
