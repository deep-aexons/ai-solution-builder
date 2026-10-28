"""Subprocess helpers shared by the verifier modules."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

_DROP_ENV = (
    "DEBUG",
    "SECRET_KEY",
    "DATABASE_URL",
    "DJANGO_SETTINGS_MODULE",
    "ALLOWED_HOSTS",
    "CSRF_COOKIE_SECURE",
    "SESSION_COOKIE_SECURE",
    "CSRF_TRUSTED_ORIGINS",
)


def clean_env(**extra: str) -> dict[str, str]:
    """The caller's environment without anything that changes the app's settings."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in _DROP_ENV and not k.startswith("ASB_ERP_")
    }
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(extra)
    return env


def as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return (
        value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    )


def tail(text: str, lines: int = 40) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else ""


def kill_group(proc: subprocess.Popen) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            continue


def run_group(
    cmd: list[str], cwd: Path, timeout: float, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run `cmd` in its own process group; on timeout kill the whole group and re-raise."""
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=max(1.0, timeout))
    except subprocess.TimeoutExpired as exc:
        kill_group(proc)
        out, _ = proc.communicate()
        raise subprocess.TimeoutExpired(cmd, timeout, output=out) from exc
    return subprocess.CompletedProcess(cmd, proc.returncode, out, "")
