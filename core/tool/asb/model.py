"""Solution model: the platform-neutral description of a business solution."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
)
from pydantic import (
    Field as PField,
)
from pydantic_core import PydanticCustomError

_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")
Name = Annotated[str, PField(pattern=r"^[a-z][a-z0-9_]*$")]
RuleId = Annotated[str, PField(pattern=r"^R\d+$")]
TestId = Annotated[str, PField(pattern=r"^AT-\d{2,}$")]
Access = Annotated[str, PField(pattern=r"^(read|write:[a-z][a-z0-9_]*)$")]

FieldType = Literal[
    "text",
    "number",
    "decimal",
    "money",
    "date",
    "datetime",
    "choice",
    "boolean",
    "attachment",
    "link",
    "external_ref",
    "table",
]
Permission = Literal[
    "create", "read", "update", "update_own_draft", "delete", "approve", "export"
]
PERMISSIONS: tuple[str, ...] = Permission.__args__  # type: ignore[attr-defined]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Field(_Base):
    name: Name
    type: FieldType
    required: bool = False
    default: Any = None
    pattern: str | None = None
    min: float | None = None
    max: float | None = None
    options: list[str] | None = None
    unique: bool = False
    read_only: bool = False
    to: list[Name] | None = None
    of: Name | None = None


class Entity(_Base):
    name: Name
    label: str
    numbering: str | None = None
    child_of: Name | None = None
    fields: list[Field]


class Transition(_Base):
    from_: Name = PField(alias="from")
    to: Name
    action: Name
    roles: list[Name]
    require: list[Name] = []


class Workflow(_Base):
    entity: Name
    states: list[Name]
    initial: Name
    final_states: list[Name] = []
    transitions: list[Transition]


class External(_Base):
    name: Name
    kind: Name
    access: Access


class Rule(_Base):
    id: RuleId
    text: str


class Report(_Base):
    name: Name
    entity: Name
    filters: list[str] = []
    columns: list[str]


class AcceptanceTest(_Base):
    id: TestId
    covers: list[str]
    text: str


class Solution(_Base):
    solution: Name
    version: int | str
    description: str
    external: list[External] = []
    entities: list[Entity]
    workflow: list[Workflow] | None = None
    roles: dict[str, dict[str, list[str]]]
    rules: list[Rule] = []
    reports: list[Report] = []
    acceptance_tests: list[AcceptanceTest]
    extensions: dict[str, Any] = {}

    @field_validator("workflow", mode="before")
    @classmethod
    def _normalise_workflow(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return [v]
        return v

    @field_validator("roles", mode="after")
    @classmethod
    def _check_roles(cls, v: dict[str, dict[str, list[str]]]):
        for role, targets in v.items():
            if not _NAME_RE.fullmatch(role):
                raise PydanticCustomError("role_name", f"invalid role name '{role}'")
            for target, perms in targets.items():
                if target == "reports":
                    continue
                for perm in perms:
                    if perm not in PERMISSIONS:
                        raise PydanticCustomError(
                            "permission",
                            "'{perm}' is not a permission; allowed: {allowed}",
                            {
                                "perm": perm,
                                "allowed": ", ".join(PERMISSIONS),
                                "path": f"{role}.{target}",
                            },
                        )
        return v

    @property
    def workflows(self) -> list[Workflow]:
        return self.workflow or []


class ModelError(Exception):
    """Raised when a solution file cannot be loaded; issues are '<path>: <message>'."""

    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


def _issues(err: ValidationError) -> list[str]:
    out = []
    for e in err.errors():
        parts = [str(p) for p in e["loc"]]
        if e["type"] == "permission":
            parts.append(e["ctx"]["path"])
        loc = ".".join(parts)
        out.append(f"{loc}: {e['msg']}")
    return out


def load_solution(path: Path) -> Solution:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise ModelError([f"{path}: {exc}"]) from exc
    if not isinstance(data, dict):
        raise ModelError([f"{path}: top level must be a mapping"])
    try:
        return Solution.model_validate(data)
    except ValidationError as exc:
        raise ModelError(_issues(exc)) from exc
