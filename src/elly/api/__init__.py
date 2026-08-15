"""Versioned, interface-neutral application contracts for Elly."""

from .application import EllyApplication
from .contracts import API_VERSION, ApiFailure, ApiFailureCode, ApiResult

__all__ = ["API_VERSION", "ApiFailure", "ApiFailureCode", "ApiResult", "EllyApplication"]
