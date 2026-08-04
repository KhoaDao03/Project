"""Small bounded in-process task executor (ADR-005 local subset)."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock, Semaphore
from typing import TypeVar

from ..domain.errors import LimitExceededError

T = TypeVar("T")


class BoundedTaskExecutor:
    """Admit at most workers plus queue slots; excess work fails closed."""

    def __init__(self, *, workers: int, queue_size: int) -> None:
        if workers <= 0 or queue_size < 0:
            raise ValueError("workers must be positive and queue_size non-negative")
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="elly-task")
        self._slots = Semaphore(workers + queue_size)
        self._lock = Lock()
        self._closed = False

    def submit(self, operation: Callable[[], T]) -> Future[T]:
        with self._lock:
            if self._closed or not self._slots.acquire(blocking=False):
                raise LimitExceededError("task queue limit exceeded")
            try:
                future = self._executor.submit(operation)
            except RuntimeError as exc:
                self._slots.release()
                raise LimitExceededError("task executor is closed") from exc
            future.add_done_callback(lambda _future: self._slots.release())
            return future

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)
