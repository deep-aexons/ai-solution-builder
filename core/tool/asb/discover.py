"""Basic ERP discovery (stage 2): what external data exists, what is missing."""

from __future__ import annotations

from dataclasses import dataclass

from asb.connector import Connector
from asb.model import Solution

SAMPLE_LIMIT = 5
HEADER = (
    "| Name | Kind | System document | Fields available | Sample records | Status |"
)
NOTES = (
    "Design only against external data marked ok; treat each gap as a "
    "requirement to resolve with the client before relying on it."
)


@dataclass
class DiscoveryReport:
    markdown: str
    connected: bool
    gaps: int


def _cell(text: object) -> str:
    """One-line, Markdown-safe rendering of any remote-derived value."""
    one = " ".join(str(text).split())
    for ch in ("\\", "`", "|"):
        one = one.replace(ch, "\\" + ch)
    return one


def _err(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _failure(exc: BaseException) -> str:
    return f"Connection failed: {_err(exc)}"


def run_discovery(
    solution: Solution, connector: Connector | None, error: Exception | None = None
) -> DiscoveryReport:
    """Inspect `connector` (or report `error` raised while building it).

    Never raises: any exception from the connector is rendered as text.
    """
    info: dict = {}
    failure = _failure(error) if error is not None else None
    if failure is None and connector is None:
        failure = "Connection failed: no connector available"
    if failure is None:
        try:
            info = connector.inspect()
            if not isinstance(info, dict):
                raise TypeError(
                    f"inspect() returned {type(info).__name__}, expected a mapping"
                )
        except Exception as exc:  # noqa: BLE001
            failure = _failure(exc)
    connected = failure is None
    kinds = info.get("kinds") if connected else {}
    if not isinstance(kinds, dict):
        kinds = {}

    rows: list[str] = []
    gaps: list[str] = []
    for ext in solution.external:
        label = f"{ext.name} ({ext.kind})"
        if not connected:
            doc, fields, sample, status = "—", "—", "not checked", "not checked"
        else:
            entry = kinds.get(ext.kind)
            reason: str | None = None
            doc, fields = "—", "0"
            if entry is None:
                reason = "kind not found in system"
            elif not isinstance(entry, dict):
                reason = f"malformed inspect entry ({type(entry).__name__})"
            else:
                doc = entry.get("doctype") or "—"
                flist = entry.get("fields", [])
                try:
                    fields = str(len(flist))
                except TypeError:
                    fields = "0"
                    reason = "malformed fields in inspect entry"
                if reason is None and entry.get("error"):
                    reason = str(entry["error"])
                elif reason is None and fields == "0":
                    reason = "no fields reported"
            try:
                sample = str(len(connector.list(ext.kind, limit=SAMPLE_LIMIT)))
            except Exception as exc:  # noqa: BLE001
                sample = f"error: {_err(exc)}"
                if reason is None:
                    reason = f"list failed: {_err(exc)}"
            status = "ok" if reason is None else f"gap: {reason}"
            if reason is not None:
                gaps.append(f"{label}: {reason}")
        rows.append(
            "| "
            + " | ".join(
                _cell(c) for c in (ext.name, ext.kind, doc, fields, sample, status)
            )
            + " |"
        )

    out = [f"# Discovery — {solution.solution}", "", "## Connection", ""]
    out.append(
        _cell(f"System version: {info.get('version', 'unknown')}")
        if connected
        else _cell(failure)
    )
    out += ["", "## External data", ""]
    if solution.external:
        out += [
            HEADER,
            "|---|---|---|---|---|---|",
            *rows,
        ]
    else:
        out.append("None declared.")
    writes = [e for e in solution.external if e.access.startswith("write:")]
    out += ["", "## Write access requested", ""]
    out += (
        [f"- {_cell(e.name)} ({_cell(e.kind)}): {_cell(e.access)}" for e in writes]
        if writes
        else ["None — read only"]
    )
    out += ["", "## Gaps", ""]
    out += [f"- {_cell(g)}" for g in gaps] if gaps else ["None"]
    out += ["", "## Notes for design", "", NOTES, ""]
    return DiscoveryReport("\n".join(out), connected, len(gaps))


def discover(solution: Solution, connector: Connector) -> str:
    """Markdown for discovery.md. Connector errors are reported, never raised."""
    return run_discovery(solution, connector).markdown
