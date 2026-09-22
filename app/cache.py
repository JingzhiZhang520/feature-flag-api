from collections import OrderedDict
from threading import Lock
from time import monotonic
from typing import Callable, Generic, Optional, Tuple, TypeVar

T = TypeVar("T")


class EvaluationCache(Generic[T]):
    """Bounded LRU cache with TTL and protection against late stale fills."""

    def __init__(self, capacity: int, ttl: float, clock: Callable[[], float] = monotonic):
        if capacity < 1 or ttl <= 0:
            raise ValueError("Cache capacity and TTL must be positive")
        self.capacity = capacity
        self.ttl = ttl
        self.clock = clock
        self._entries: OrderedDict[Tuple[str, str], Tuple[float, T]] = OrderedDict()
        self._generation = 0
        self._lock = Lock()

    def get(self, key: Tuple[str, str]) -> Tuple[Optional[T], int]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                expires_at, value = entry
                if self.clock() < expires_at:
                    self._entries.move_to_end(key)
                    return value, self._generation
                del self._entries[key]
            return None, self._generation

    def put(self, key: Tuple[str, str], value: T, generation: int) -> None:
        with self._lock:
            # A write committed while the database read was in flight.
            if generation != self._generation:
                return
            self._entries[key] = (self.clock() + self.ttl, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self.capacity:
                self._entries.popitem(last=False)

    def invalidate(self) -> None:
        with self._lock:
            self._generation += 1
            self._entries.clear()
