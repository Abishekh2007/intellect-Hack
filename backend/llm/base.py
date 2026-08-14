"""Shared provider exceptions."""

from __future__ import annotations


class ProviderError(Exception):
    """Raised for auth, quota, transport or SDK failures.

    ``error_type`` and ``message`` are user-safe (never leak keys/paths).
    """

    def __init__(self, error_type: str, message: str):
        super().__init__(message)
        self.error_type = error_type
        self.message = message


class AllProvidersFailed(Exception):
    pass