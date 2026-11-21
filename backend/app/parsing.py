"""HTML 파싱 같은 CPU 작업을 스레드에서 실행하되 동시 실행 수를 제한한다.

`run_limited(limiter, fn, *args)`
- `limiter`(예: `anyio.CapacityLimiter(1)`)의 자리를 얻은 뒤 `fn`을 작업 스레드에서 실행한다.
- 기다리는 쪽(요청)이 시간 초과 등으로 취소되면 **기다림만 끝나고**, 스레드에서 이미 시작한 파싱은
  끝까지 돈다 (파이썬 스레드는 중간에 멈출 수 없다). 이때도 자리는 파싱이 실제로 끝날 때 반납한다.
  → 시간 초과가 반복돼도 파싱 스레드가 `limiter` 크기보다 많이 쌓이지 않는다 (1코어·1GB 서버 보호).
- 자리를 기다리는 동안 취소되면 파싱을 시작하지 않는다.
"""

import asyncio
from collections.abc import Callable

import anyio
import anyio.to_thread

# 기다리는 쪽이 사라진 뒤에도 끝까지 도는 파싱 작업 (가비지 컬렉션 방지용 참조).
_running: set[asyncio.Task[object]] = set()


async def _run_and_release[T](
    limiter: anyio.CapacityLimiter, token: object, fn: Callable[..., T], args: tuple[object, ...]
) -> T:
    try:
        # abandon_on_cancel=False(기본): 이 작업이 취소돼도 스레드가 끝날 때까지 기다린 뒤 반납한다.
        return await anyio.to_thread.run_sync(fn, *args)
    finally:
        limiter.release_on_behalf_of(token)


def _forget(task: asyncio.Task[object]) -> None:
    _running.discard(task)
    if not task.cancelled():
        task.exception()  # 기다리는 쪽이 없을 때 "예외를 아무도 읽지 않음" 경고가 나지 않게


async def run_limited[T](limiter: anyio.CapacityLimiter, fn: Callable[..., T], *args: object) -> T:
    token = object()
    await limiter.acquire_on_behalf_of(token)
    try:
        task: asyncio.Task[T] = asyncio.ensure_future(_run_and_release(limiter, token, fn, args))
    except BaseException:
        limiter.release_on_behalf_of(token)
        raise
    _running.add(task)
    task.add_done_callback(_forget)
    # shield: 기다리는 쪽이 취소돼도 작업(과 자리)은 파싱이 끝날 때까지 유지된다.
    return await asyncio.shield(task)
