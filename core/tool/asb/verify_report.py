"""Render the stage 5 verify report (verify-report.md)."""

from __future__ import annotations

from datetime import UTC, datetime

from asb.plugins import VerifyResult
from asb.status import MAX_VERIFY_ROUNDS


def _cell(text: str) -> str:
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first.replace("|", "\\|")


def passed(result: VerifyResult) -> bool:
    return not any(c.status == "fail" for c in result.checks)


def render_report(
    solution: str, round_no: int, result: VerifyResult, now: datetime | None = None
) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"# Verify report — {solution} (round {round_no} of {MAX_VERIFY_ROUNDS})",
        "",
        f"Generated at: {stamp}",
        "",
        "| Check | Status | Details |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {c.name} | {c.status} | {_cell(c.details)} |" for c in result.checks]
    failed = [c for c in result.checks if c.status == "fail"]
    skipped = [c for c in result.checks if c.status == "skipped"]
    lines += ["", "## Failures", ""]
    if failed:
        for c in failed:
            lines += [f"### {c.name}", "", "```", c.details.strip(), "```", ""]
    else:
        lines += ["None.", ""]
    lines += ["## Skipped", ""]
    if skipped:
        lines += [f"- {c.name}: {c.details.strip()}" for c in skipped]
    else:
        lines.append("None.")
    lines += ["", f"Result: {'PASS' if passed(result) else 'FAIL'}", ""]
    return "\n".join(lines)
