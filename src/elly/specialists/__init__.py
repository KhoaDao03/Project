"""Configuration-driven specialist registry foundation.

Specialist execution and routing are intentionally deferred to M5. This package
only validates and discovers manifests so later capabilities have one stable seam.
"""

from .manifest import SpecialistManifest
from .registry import SpecialistRegistry

__all__ = ["SpecialistManifest", "SpecialistRegistry"]
