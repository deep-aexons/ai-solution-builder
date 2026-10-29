"""ERPNext REST client implementing the asb Connector protocol.

Imports only stdlib, httpx, yaml and asb.connector (vendored into apps).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
import yaml

from asb.connector import (
    AuthFailed,
    ConnectorError,
    NotFound,
    Unavailable,
    WriteNotApproved,
)

_MAPPING = yaml.safe_load((Path(__file__).parent / "mapping.yaml").read_text())
_ATTEMPTS = 3
_RETRY_STATUS = {429}
_NETWORK_ERRORS = (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout)


def _server_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        for key in ("exception", "_server_messages", "message"):
            if body.get(key):
                return str(body[key])
    return resp.text[:200] or f"HTTP {resp.status_code}"


class ERPNextConnector:
    def __init__(
        self,
        url: str,
        api_key: str,
        api_secret: str,
        allowed_writes: Iterable[str] = frozenset(),
        timeout: float = 15,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.url = url.rstrip("/")
        self.allowed_writes = set(allowed_writes)
        self._sleep = sleep
        self._kinds: dict[str, str] = dict(_MAPPING["kinds"])
        self._states: dict[int, str] = {
            int(k): v for k, v in _MAPPING["states"]["docstatus"].items()
        }
        self._http = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"token {api_key}:{api_secret}"},
        )

    def __repr__(self) -> str:
        parts = urlsplit(self.url)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        shown = urlunsplit((parts.scheme, host, parts.path, "", ""))
        return f"ERPNextConnector(url={shown!r})"

    @classmethod
    def from_env(
        cls, allowed_writes: Iterable[str] = frozenset(), **kw: Any
    ) -> ERPNextConnector:
        values = []
        for name in ("ASB_ERP_URL", "ASB_ERP_API_KEY", "ASB_ERP_API_SECRET"):
            value = os.environ.get(name)
            if not value:
                raise ConnectorError(f"missing environment variable {name}")
            values.append(value)
        return cls(*values, allowed_writes=allowed_writes, **kw)

    # -- helpers -----------------------------------------------------------

    def _doctype(self, kind: str) -> str:
        try:
            return self._kinds[kind]
        except KeyError:
            raise ConnectorError(
                f"unknown kind {kind!r}; known kinds: {', '.join(sorted(self._kinds))}"
            ) from None

    def _with_state(self, record: dict[str, Any]) -> dict[str, Any]:
        if record.get("docstatus") is not None:
            try:
                record["_state"] = self._states.get(int(record["docstatus"]), "unknown")
            except (TypeError, ValueError):
                raise ConnectorError(
                    f"unexpected ERPNext response: bad docstatus {record['docstatus']!r}"
                ) from None
        return record

    @staticmethod
    def _data(body: Any, expected: type) -> Any:
        data = body.get("data", None) if isinstance(body, dict) else None
        if not isinstance(data, expected):
            raise ConnectorError(
                f"unexpected ERPNext response: expected {expected.__name__} under 'data'"
            )
        return data

    def _request(self, method: str, path: str, **kw: Any) -> Any:
        url = f"{self.url}{path}"
        last = "no response"
        for attempt in range(_ATTEMPTS):
            if attempt:
                self._sleep(0.5 * 2 ** (attempt - 1))
            try:
                resp = self._http.request(method, url, **kw)
            except _NETWORK_ERRORS as exc:
                # POST is only safe to retry when the request never connected.
                retryable = method == "GET" or isinstance(exc, httpx.ConnectError)
                last = f"{type(exc).__name__}: {exc}"
                if retryable:
                    continue
                raise Unavailable(f"ERPNext unreachable: {last}") from exc
            except httpx.HTTPError as exc:
                raise Unavailable(f"ERPNext request failed: {exc}") from exc
            status = resp.status_code
            if status in (401, 403):
                raise AuthFailed(f"ERPNext rejected credentials (HTTP {status})")
            if status == 404:
                raise NotFound(_server_message(resp))
            if status in _RETRY_STATUS or status >= 500:
                last = f"HTTP {status}"
                if method == "GET":
                    continue
                raise Unavailable(f"ERPNext error: {last}")
            if status >= 400:
                raise ConnectorError(
                    f"ERPNext error (HTTP {status}): {_server_message(resp)}"
                )
            try:
                return resp.json()
            except ValueError as exc:
                raise ConnectorError("ERPNext returned a non-JSON response") from exc
        raise Unavailable(f"ERPNext unavailable after {_ATTEMPTS} attempts: {last}")

    # -- Connector protocol -------------------------------------------------

    def inspect(self) -> dict[str, Any]:
        try:
            body = self._request(
                "GET", "/api/method/frappe.utils.change_log.get_versions"
            )
            version = str(body["message"]["frappe"]["version"])
        except AuthFailed:
            raise
        except (ConnectorError, KeyError, TypeError):
            version = "unknown"
        kinds: dict[str, Any] = {}
        for kind, doctype in self._kinds.items():
            try:
                body = self._request(
                    "GET",
                    "/api/method/frappe.desk.form.load.getdoctype",
                    params={"doctype": doctype},
                )
                fields = [f["fieldname"] for f in body["message"]["docs"][0]["fields"]]
                kinds[kind] = {"document": doctype, "fields": fields}
            except AuthFailed:
                raise
            except (ConnectorError, KeyError, IndexError, TypeError) as exc:
                kinds[kind] = {"document": doctype, "fields": [], "error": str(exc)}
        return {"version": version, "kinds": kinds}

    def get(self, kind: str, id: str) -> dict[str, Any]:
        doctype = self._doctype(kind)
        if not isinstance(id, str) or id.strip() in ("", ".", ".."):
            raise ConnectorError(f"invalid document id {id!r}")
        body = self._request(
            "GET", f"/api/resource/{quote(doctype)}/{quote(id, safe='')}"
        )
        return self._with_state(dict(self._data(body, dict)))

    def list(
        self,
        kind: str,
        filters: dict[str, Any] | list[Any] | None = None,
        fields: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        doctype = self._doctype(kind)
        if isinstance(filters, dict):
            filters = [[k, "=", v] for k, v in filters.items()]
        params = {
            "filters": json.dumps(filters or []),
            "fields": json.dumps(fields or ["name"]),
            "limit_page_length": limit,
        }
        body = self._request("GET", f"/api/resource/{quote(doctype)}", params=params)
        rows = self._data(body, list)
        if not all(isinstance(r, dict) for r in rows):
            raise ConnectorError("unexpected ERPNext response: rows must be objects")
        return [self._with_state(dict(row)) for row in rows]

    def create_draft(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        doctype = self._doctype(kind)
        if f"write:{kind}" not in self.allowed_writes:
            raise WriteNotApproved(
                f"write:{kind} is not approved in the solution model"
            )
        payload = {k: v for k, v in data.items() if k not in ("docstatus", "name")}
        body = self._request("POST", f"/api/resource/{quote(doctype)}", json=payload)
        return self._with_state(dict(self._data(body, dict)))
