"""Request-scoped cancellation shared by application workflows and adapters."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, Lock

from ...domain.errors import CancelledError


class CancellationToken:
    """Thread-safe cooperative cancellation with interrupt callbacks."""

    def __init__(self) -> None:
        self._event = Event()
        self._lock = Lock()
        self._callbacks: set[Callable[[], None]] = set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise CancelledError("operation cancelled by owner")

    def register(self, callback: Callable[[], None]) -> Callable[[], None]:
        with self._lock:
            if self._event.is_set():
                callback()
                return lambda: None
            self._callbacks.add(callback)
        return lambda: self.unregister(callback)

    def unregister(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._callbacks.discard(callback)

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            callbacks = tuple(self._callbacks)
        for callback in callbacks:
            try:
                callback()
            except Exception:
                continue
