"""Per-solution status, approvals and stage gates.

Status files assume one asb process per solution at a time (no locking).
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ValidationError

from asb.model import ModelError, parse_solution

STAGES = ["requirements", "discovery", "design", "build", "verify", "release"]
MAX_VERIFY_ROUNDS = 3
_NAME_RE = re.compile(r"[a-z][a-z0-9-]*")

ApprovalKind = Literal["requirements", "design", "client", "golive"]
APPROVAL_KINDS: tuple[str, ...] = get_args(ApprovalKind)


class GateError(Exception):
    """Raised when a stage may not start yet."""


class Approval(BaseModel):
    kind: ApprovalKind
    by: str
    at: datetime
    model_version: str | None = None
    model_hash: str | None = None


class Status(BaseModel):
    solution: str
    pack: str
    connector: str | None = None
    stages: dict[str, Literal["todo", "done"]]
    approvals: list[Approval] = []
    verify_rounds: int = 0


def _now() -> datetime:
    return datetime.now(UTC)


def log_event(sol_dir: Path, event: str, detail: str) -> None:
    ts = _now().isoformat(timespec="seconds").replace("+00:00", "Z")
    detail = detail.replace("\t", " ").replace("\n", " ")
    with (Path(sol_dir) / "audit.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{ts}\t{event}\t{detail}\n")


def load_status(sol_dir: Path) -> Status:
    path = Path(sol_dir) / "status.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise GateError(f"status.json not found: {path}") from exc
    except OSError as exc:
        raise GateError(f"status.json unreadable: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise GateError(f"status.json is corrupt: {exc}") from exc
    try:
        return Status.model_validate_json(raw)
    except ValidationError as exc:
        first = (str(exc).splitlines() or [type(exc).__name__])[0]
        raise GateError(f"status.json is corrupt: {first}") from exc


def save_status(sol_dir: Path, status: Status) -> None:
    """Write status.json atomically (temp file, fsync, replace)."""
    sol_dir = Path(sol_dir)
    fd, tmp = tempfile.mkstemp(dir=sol_dir, prefix=".status-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(status.model_dump_json(indent=2) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, sol_dir / "status.json")
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def new_solution(root: Path, name: str, pack: str, connector: str | None) -> Path:
    if not valid_name(name):
        raise ValueError(f"invalid solution name '{name}': use ^[a-z][a-z0-9-]*$")
    sol_dir = Path(root) / "solutions" / name
    if sol_dir.exists():
        raise FileExistsError(f"solution folder already exists: {sol_dir}")
    (sol_dir / "design").mkdir(parents=True)
    (sol_dir / "design" / ".gitkeep").touch()
    (sol_dir / "requirements.md").write_text(
        f"# Requirements: {name}\n", encoding="utf-8"
    )
    (sol_dir / "discovery.md").write_text(f"# Discovery: {name}\n", encoding="utf-8")
    (sol_dir / "audit.log").touch()
    save_status(
        sol_dir,
        Status(
            solution=name,
            pack=pack,
            connector=connector,
            stages={s: "todo" for s in STAGES},
        ),
    )
    log_event(sol_dir, "new", f"pack={pack} connector={connector}")
    set_active(root, name)
    return sol_dir


def set_active(root: Path, name: str) -> None:
    """Make `name` the active solution (read by the PreToolUse hook)."""
    if not valid_name(name):
        raise ValueError(f"invalid solution name '{name}': use ^[a-z][a-z0-9-]*$")
    folder = Path(root) / ".asb"
    folder.mkdir(exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".active-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(name + "\n")
        os.replace(tmp, folder / "active")
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def clear_active(root: Path) -> None:
    (Path(root) / ".asb" / "active").unlink(missing_ok=True)


def model_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mark_done(sol_dir: Path, stage: str) -> None:
    if stage not in STAGES:
        raise ValueError(f"unknown stage '{stage}'")
    st = load_status(sol_dir)
    st.stages[stage] = "done"
    save_status(sol_dir, st)
    log_event(sol_dir, "mark_done", stage)


def mark_todo(sol_dir: Path, stage: str) -> None:
    if stage not in STAGES:
        raise ValueError(f"unknown stage '{stage}'")
    st = load_status(sol_dir)
    st.stages[stage] = "todo"
    save_status(sol_dir, st)
    log_event(sol_dir, "mark_todo", stage)


def increment_verify_rounds(sol_dir: Path) -> int:
    st = load_status(sol_dir)
    st.verify_rounds += 1
    save_status(sol_dir, st)
    log_event(sol_dir, "verify_round", str(st.verify_rounds))
    return st.verify_rounds


def reset_verify(sol_dir: Path) -> None:
    """A new build starts a new verify cycle: rounds back to 0, verify stage to todo."""
    st = load_status(sol_dir)
    st.verify_rounds = 0
    st.stages["verify"] = "todo"
    save_status(sol_dir, st)
    log_event(sol_dir, "verify_reset", "new build")


def approve(sol_dir: Path, kind: str, by: str) -> Approval:
    sol_dir = Path(sol_dir)
    if kind not in APPROVAL_KINDS:
        raise ValueError(
            f"unknown approval kind '{kind}'; allowed: {', '.join(APPROVAL_KINDS)}"
        )
    version: str | None = None
    digest: str | None = None
    if kind == "design":
        path = sol_dir / "design" / "solution.yaml"
        if not path.is_file():
            _fail(sol_dir, "approve design", "design/solution.yaml does not exist")
        raw = path.read_bytes()
        try:
            sol = parse_solution(raw, path)
        except ModelError as exc:
            _fail(
                sol_dir,
                "approve design",
                "design/solution.yaml is invalid: " + "; ".join(exc.issues),
            )
        version = str(sol.version)
        digest = hashlib.sha256(raw).hexdigest()
    approval = Approval(
        kind=kind,
        by=by,
        at=_now(),
        model_version=version,
        model_hash=digest,
    )
    st = load_status(sol_dir)
    st.approvals.append(approval)
    if kind in ("requirements", "design"):
        st.stages[kind] = "done"  # approving a stage's output completes the stage
    save_status(sol_dir, st)
    log_event(sol_dir, "approve", f"{kind} by {by} hash={digest}")
    return approval


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.fullmatch(name))


def _fail(sol_dir: Path, what: str, message: str):
    log_event(sol_dir, "gate_failed", f"{what}: {message}")
    raise GateError(message)


def _latest(st: Status, kind: str) -> Approval | None:
    found = [a for a in st.approvals if a.kind == kind]
    return found[-1] if found else None


def require(sol_dir: Path, stage: str) -> None:
    """Raise GateError unless `stage` may start."""
    sol_dir = Path(sol_dir)
    if stage not in STAGES:
        raise ValueError(f"unknown stage '{stage}'")
    st = load_status(sol_dir)

    def fail(message: str):
        _fail(sol_dir, stage, message)

    if stage == "design":
        if _latest(st, "requirements") is None:
            fail("requirements not approved")
    elif stage == "build":
        approval = _latest(st, "design")
        if approval is None:
            fail("design not approved")
        path = sol_dir / "design" / "solution.yaml"
        if not path.is_file() or model_hash(path) != approval.model_hash:
            fail("design changed since approval: approved hash differs; re-approve")
    elif stage == "verify":
        if st.stages.get("build") != "done":
            fail("build not done")
        if st.verify_rounds >= MAX_VERIFY_ROUNDS:
            fail(
                f"fix-loop limit reached ({MAX_VERIFY_ROUNDS} rounds); "
                "escalate to a human"
            )
    elif stage == "release":
        if st.stages.get("verify") != "done":
            fail("verify not done")
        if _latest(st, "client") is None:
            fail("client not approved")
