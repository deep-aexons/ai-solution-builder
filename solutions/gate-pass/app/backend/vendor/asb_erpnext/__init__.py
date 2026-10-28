"""ERPNext connector: REST reads, approved draft creates, no delete/submit/cancel."""

from __future__ import annotations

from collections.abc import Iterable

from .client import ERPNextConnector


def from_env(allowed_writes: Iterable[str] = frozenset()) -> ERPNextConnector:
    return ERPNextConnector.from_env(allowed_writes=allowed_writes)


__all__ = ["ERPNextConnector", "from_env"]
