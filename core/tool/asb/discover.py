"""Basic ERP discovery (stage 2): what external data exists, what is missing."""

from __future__ import annotations

from dataclasses import dataclass

from asb.connector import Connector, ConnectorError
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
    return " ".join(str(text).split()).replace("|", "\\|")


def _failure(exc: Exception) -> str:
    return f"Connection failed: {type(exc).__name__}: {exc}"


def run_discovery(
    solution: Solution, connector: Connector | None, error: Exception | None = None
) -> DiscoveryReport:
    """Inspect `connector` (or report `error` raised while building it)."""
    info: dict = {}
    failure = _failure(error) if error is not None else None
    if failure is None and connector is not None:
        try:
            info = connector.inspect()
        except ConnectorError as exc:
            failure = _failure(exc)
    connected = failure is None
    kinds = info.get("kinds", {}) if connected else {}

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
            else:
                doc = entry.get("doctype") or "—"
                fields = str(len(entry.get("fields", [])))
                if entry.get("error"):
                    reason = str(entry["error"])
                elif fields == "0":
                    reason = "no fields reported"
            try:
                sample = str(len(connector.list(ext.kind, limit=SAMPLE_LIMIT)))
            except ConnectorError as exc:
                sample = f"error: {exc}"
                if reason is None:
                    reason = f"list failed: {exc}"
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
        f"System version: {info.get('version', 'unknown')}" if connected else failure
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
        [f"- {e.name} ({e.kind}): {e.access}" for e in writes]
        if writes
        else ["None — read only"]
    )
    out += ["", "## Gaps", ""]
    out += [f"- {g}" for g in gaps] if gaps else ["None"]
    out += ["", "## Notes for design", "", NOTES, ""]
    return DiscoveryReport("\n".join(out), connected, len(gaps))


def discover(solution: Solution, connector: Connector) -> str:
    """Markdown for discovery.md. Connector errors are reported, never raised."""
    return run_discovery(solution, connector).markdown
