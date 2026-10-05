"""Errors an exchange reports – shared by the Revolut X and the Trade Republic client."""

from __future__ import annotations


class ExchangeError(Exception):
    """The exchange answered, but with an error. ``status`` follows HTTP (404 = unknown order, 429 = rate limit)."""

    venue = "Exchange"

    def __init__(self, status: int, message: str):
        super().__init__(f"{self.venue} {status}: {message}")
        self.status = status
        self.message = message

    @property
    def transient(self) -> bool:
        """Rate limit or server-side problem – worth retrying, says nothing about the request itself."""
        return self.status == 429 or self.status >= 500
