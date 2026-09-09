import threading
from collections import deque
from typing import Any


class RingBuffer:
    """Thread-safe fixed-size circular buffer for the live timeline scrubber.

    Sized for 100 frames (5s @ 20Hz) by default. Push is O(1); snapshot()
    returns a shallow copy so callers can iterate without holding the lock.
    """

    def __init__(self, maxsize: int = 100) -> None:
        self._buf: deque[Any] = deque(maxlen=maxsize)
        self._lock = threading.Lock()

    def push(self, item: Any) -> None:
        with self._lock:
            self._buf.append(item)

    def snapshot(self) -> list[Any]:
        with self._lock:
            return list(self._buf)

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)
