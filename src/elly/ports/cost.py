"""Cost reservation port; M3 uses a deterministic fake implementation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CostPort(Protocol):
    """Reserve estimated cost before a provider call and reconcile afterward."""

    def reserve(self, amount_usd: float) -> None:
        """Raise a typed limit error if the approved budget cannot cover the call."""
        ...

    def reconcile(self, reserved_usd: float, actual_usd: float) -> None:
        """Replace the reservation with the observed/configured cost."""
        ...
