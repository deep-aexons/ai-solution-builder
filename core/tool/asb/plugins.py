"""Load platform packs (how to build) and connectors (how to reach an ERP) by path."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

import yaml


@dataclass
class GenerateResult:
    written: list[str] = field(default_factory=list)
    skipped_ai_owned: list[str] = field(default_factory=list)


@dataclass
class CheckResult:
    name: str
    status: Literal["pass", "fail", "skipped"]
    details: str = ""


@dataclass
class VerifyResult:
    checks: list[CheckResult] = field(default_factory=list)


@dataclass
class Pack:
    name: str
    path: Path
    capabilities: dict[str, Any]
    module: ModuleType

    def generate(
        self, solution: Any, solution_dir: Path, **kwargs: Any
    ) -> GenerateResult:
        return self.module.generate(solution, solution_dir, **kwargs)

    def verify(self, solution: Any, solution_dir: Path, **kwargs: Any) -> VerifyResult:
        return self.module.verify(solution, solution_dir, **kwargs)


@dataclass
class ConnectorInfo:
    name: str
    path: Path
    kinds: dict[str, str]
    module: ModuleType | None = None
    entry: str = ""


def _read_yaml(path: Path, required: tuple[str, ...]) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping")  # noqa: TRY004
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"{path}: missing key(s): {', '.join(missing)}")
    return data


def _import_entry(folder: Path, entry: str) -> ModuleType:
    where = str(folder)
    if where not in sys.path:
        sys.path.insert(0, where)
    return importlib.import_module(entry)


def load_pack(root: Path, name: str) -> Pack:
    folder = Path(root) / "packs" / name
    data = _read_yaml(
        folder / "pack.yaml",
        ("name", "entry", "field_types", "workflow", "reports", "permissions"),
    )
    capabilities = {
        "field_types": list(data["field_types"]),
        "workflow": bool(data["workflow"]),
        "reports": bool(data["reports"]),
        "permissions": list(data["permissions"]),
    }
    module = _import_entry(folder, data["entry"])
    return Pack(str(data["name"]), folder, capabilities, module)


def read_connector_info(root: Path, name: str) -> ConnectorInfo:
    """Read connector.yaml without importing the connector package."""
    folder = Path(root) / "connectors" / name
    data = _read_yaml(folder / "connector.yaml", ("name", "entry", "kinds"))
    return ConnectorInfo(
        str(data["name"]), folder, dict(data["kinds"]), None, str(data["entry"])
    )


def load_connector(root: Path, name: str) -> ConnectorInfo:
    info = read_connector_info(root, name)
    info.module = _import_entry(info.path, info.entry)
    return info
