"""Vendoring: the neutral connector contract and the solution's ERP connector."""

from __future__ import annotations

from pathlib import Path

import asb.connector
from asb.plugins import ConnectorInfo, read_connector_info
from asb.status import load_status


def resolve_connector(solution_dir: Path, root: Path) -> ConnectorInfo | None:
    """The connector named in status.json, or None when there is none."""
    if not (solution_dir / "status.json").is_file():
        return None
    name = load_status(solution_dir).connector
    if not name:
        return None
    return read_connector_info(root, name)


def vendored_files(info: ConnectorInfo | None) -> dict[str, bytes]:
    """Backend-relative path -> bytes, copied verbatim (no header)."""
    files = {
        "vendor/asb/__init__.py": b"",
        "vendor/asb/connector.py": Path(asb.connector.__file__).read_bytes(),
    }
    if info is not None:
        package = info.path / info.entry
        for path in sorted(package.rglob("*")):
            parts = path.relative_to(package).parts
            if path.is_file() and "__pycache__" not in parts and path.suffix != ".pyc":
                files[f"vendor/{info.entry}/{'/'.join(parts)}"] = path.read_bytes()
    return files
