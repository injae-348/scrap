"""상한과 만료가 있는 메모리 저장소.

uvicorn 워커가 1개라 프로세스 메모리에 둬도 요청 간에 공유된다. 재시작하면 사라진다
(가입 대기·로그인 challenge·TOTP 재설정 대기는 몇 분짜리라 처음부터 다시 하면 된다).
크기 상한을 넘으면 만료된 것부터, 그래도 넘으면 가장 오래된 것부터 버린다
→ 메모리가 무한히 늘지 않는다.
"""

import threading
from collections import OrderedDict

from app.clock import Clock


class TTLStore[V]:
    def __init__(self, clock: Clock, ttl_seconds: float, max_items: int) -> None:
        self._clock = clock
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self._items: OrderedDict[str, tuple[float, V]] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, key: str, value: V) -> None:
        now = self._clock.now()
        with self._lock:
            self._items.pop(key, None)
            self._purge_expired(now)
            while len(self._items) >= self.max_items:
                self._items.popitem(last=False)
            self._items[key] = (now + self.ttl_seconds, value)

    def get(self, key: str) -> V | None:
        now = self._clock.now()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires_at, value = item
            if now >= expires_at:
                del self._items[key]
                return None
            return value

    def pop(self, key: str) -> V | None:
        value = self.get(key)
        with self._lock:
            self._items.pop(key, None)
        return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def _purge_expired(self, now: float) -> None:
        expired = [k for k, (exp, _) in self._items.items() if now >= exp]
        for key in expired:
            del self._items[key]
