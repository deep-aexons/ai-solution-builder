"""Neutral connector contract.

Stdlib only: this file is vendored verbatim into generated apps.
There is deliberately no delete, submit or cancel operation.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class ConnectorError(Exception):
    """Base class for connector failures."""


class NotFound(ConnectorError):
    """The requested document or kind does not exist."""


class Unavailable(ConnectorError):
    """The system could not be reached or answered with a transient error."""


class AuthFailed(ConnectorError):
    """Credentials were missing or rejected."""


class WriteNotApproved(ConnectorError):
    """A write was attempted that the approved model does not allow."""


@runtime_checkable
class Connector(Protocol):
    def inspect(self) -> dict[str, Any]: ...

    def get(self, kind: str, id: str) -> dict[str, Any]: ...

    def list(
        self,
        kind: str,
        filters: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...

    def create_draft(self, kind: str, data: dict[str, Any]) -> dict[str, Any]: ...
