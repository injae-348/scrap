"""Claude API 호출 (서버 전용). docs/API.md v1.5 "AI 세부 규칙 > 공통".

- 키는 설정(`ANTHROPIC_API_KEY`)에서만 받는다. 키가 유효할 때만, 처음 쓸 때 SDK를 불러와
  클라이언트를 만든다 (AI를 쓰지 않으면 SDK가 메모리를 차지하지 않는다).
- 키는 이 객체의 `repr`·로그·예외 메시지에 넣지 않는다. 실패 로그에는 예외 종류·상태 코드·
  오류 종류·요청 id만 남긴다 (외부 오류 원문·본문·검색어는 남기지 않는다).
- 서버측 거부 대비(`fallbacks: "default"`, 베타 `server-side-fallback-2026-07-01`)를 기본으로
  넣는다 (설정 `ANTHROPIC_FALLBACKS=0`이면 헤더와 매개변수를 모두 뺀다). 안전 분류기가 거부하면
  API가 같은 요청을 Anthropic이 권하는 다른 모델로 다시 실행한다.
  그래도 `stop_reason: "refusal"`이면 실패(502)다.
- 재시도: SDK 자동 재시도는 끄고(`max_retries=0`) 여기서 한 번만 다시 시도한다 (연결 오류·408·409·
  429·5xx). 사용 한도·결제 문제(`AiQuotaExceeded`)는 다시 시도해도 풀리지 않으므로 바로 끝낸다.
  모든 시도는 호출한 쪽이 정한 마감 시각 안에서만 한다.
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("app")

FALLBACK_BETA = "server-side-fallback-2026-07-01"
RETRY_DELAY_SECONDS = 1.0
MAX_ATTEMPTS = 2
_RETRY_STATUSES = frozenset({408, 409, 429})

ClientFactory = Callable[[str], Any]


class AiFailed(Exception):
    """AI 응답을 받지 못함 → 502 `ai_failed`. 인자는 로그용 짧은 원인 (외부 원문 아님)."""


class AiQuotaExceeded(Exception):
    """사용 한도·결제 문제 → 503 `ai_quota_exceeded`. 인자는 원인 종류."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


def _default_factory(api_key: str) -> Any:
    import anthropic  # 처음 쓸 때만 불러온다 (메모리)

    # timeout 은 요청마다 남은 시간으로 넘긴다. 재시도는 ClaudeGateway 가 한다.
    return anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)


def quota_kind(exc: BaseException) -> str | None:
    """사용 한도·결제 문제로 받지 않은 요청이면 원인 종류, 아니면 None.

    SDK 예외 종류로 먼저 나눈 뒤 오류 본문(`type`, `details.error_code`, `message`)으로 확인한다.
    """
    try:
        import anthropic
    except ImportError:  # pragma: no cover - 설치돼 있다
        return None
    if not isinstance(exc, anthropic.APIStatusError):
        return None
    error_type = getattr(exc, "type", None)
    message = getattr(exc, "api_message", None) or ""
    if isinstance(exc, anthropic.RateLimitError):
        if (
            error_type == "rate_limit_error"
            and getattr(exc, "error_code", None) == "enforced_spend_limit_reached"
        ):
            return "tier_cap"
        return None
    if exc.status_code == 402 and error_type == "billing_error":
        return "billing"
    if isinstance(exc, anthropic.BadRequestError) and error_type == "invalid_request_error":
        if message.startswith("You have reached your specified"):
            return "spend_limit"
        if "credit balance" in message:
            return "credit"
    return None


def _retryable(exc: BaseException) -> bool:
    import anthropic

    if isinstance(exc, anthropic.APIConnectionError):  # 시간 초과 포함
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in _RETRY_STATUSES or exc.status_code >= 500
    return False


def _describe(exc: BaseException) -> str:
    """로그용: 예외 종류·상태 코드·오류 종류·요청 id (메시지 원문은 넣지 않는다)."""
    parts = [type(exc).__name__]
    for attr in ("status_code", "type", "request_id"):
        value = getattr(exc, attr, None)
        if isinstance(value, str | int) and not isinstance(value, bool):
            parts.append(f"{attr}={value}")
    return " ".join(parts)


class ClaudeGateway:
    """앱마다 하나(`app.state.ai_gateway`). 테스트는 `client_factory`로 가짜 클라이언트를 넣는다."""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        client_factory: ClientFactory | None = None,
        fallbacks: bool = True,
    ) -> None:
        self.__api_key = api_key
        self.model = model
        self.fallbacks = fallbacks
        self._factory = client_factory or _default_factory
        self._client: Any = None

    def __repr__(self) -> str:
        return f"ClaudeGateway(model={self.model!r}, available={self.available})"

    @property
    def available(self) -> bool:
        return self.__api_key is not None

    def _get_client(self) -> Any:
        if self.__api_key is None:
            raise AiFailed("not configured")
        if self._client is None:
            self._client = self._factory(self.__api_key)
        return self._client

    async def create(self, params: dict[str, Any], deadline: float) -> Any:
        """`messages.create`(베타 + fallbacks). `deadline`은 `time.monotonic()` 기준 마감 시각."""
        client = self._get_client()
        request: dict[str, Any] = {**params, "model": self.model}
        if self.fallbacks:
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AiFailed("deadline")
            try:
                return await client.beta.messages.create(**request, timeout=remaining)
            except Exception as exc:  # noqa: BLE001 — 외부 API 실패는 모두 502/503으로 바꾼다
                kind = quota_kind(exc)
                if kind is not None:
                    logger.warning("Claude API 사용 한도 도달: %s", kind)
                    raise AiQuotaExceeded(kind) from None
                logger.warning("Claude API 호출 실패 (%d회째): %s", attempt, _describe(exc))
                if attempt >= MAX_ATTEMPTS or not _retryable(exc):
                    raise AiFailed("api error") from None
                if deadline - time.monotonic() <= RETRY_DELAY_SECONDS:
                    raise AiFailed("deadline") from None
                await asyncio.sleep(RETRY_DELAY_SECONDS)
        raise AiFailed("unreachable")  # pragma: no cover


# ── 응답 해석 ────────────────────────────────────────


def check_stop_reason(response: Any, allowed: frozenset[str]) -> str:
    """`stop_reason`을 먼저 본다. 거부·길이 초과·예상 밖 값이면 `AiFailed`."""
    reason = getattr(response, "stop_reason", None)
    if reason == "refusal":
        logger.warning("Claude가 답변을 거부했습니다.")
        raise AiFailed("refusal")
    if reason not in allowed:
        logger.warning("Claude 응답 종료 사유가 예상과 다릅니다: %s", str(reason)[:40])
        raise AiFailed("stop reason")
    return str(reason)


def blocks(response: Any, kind: str) -> list[Any]:
    content = getattr(response, "content", None) or []
    return [b for b in content if getattr(b, "type", None) == kind]


def response_json(response: Any) -> dict[str, Any]:
    """구조화 출력(JSON 스키마)의 텍스트 → dict. 형식 위반이면 `AiFailed`."""
    text = "".join(str(getattr(b, "text", "")) for b in blocks(response, "text")).strip()
    try:
        data = json.loads(text)
    except ValueError:
        logger.warning("Claude 응답이 JSON 형식이 아닙니다.")
        raise AiFailed("bad json") from None
    if not isinstance(data, dict):
        raise AiFailed("bad json")
    return data
