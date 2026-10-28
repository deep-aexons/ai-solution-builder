"""Errors raised by the sidecar generator."""

from __future__ import annotations


class OrphanFileError(Exception):
    """AI-owned files exist whose rule, report or acceptance test left the model."""

    def __init__(self, paths: list[str]):
        self.paths = sorted(paths)
        super().__init__(
            "AI-owned files no longer match the model (move or delete them, "
            "nothing was written): " + ", ".join(self.paths)
        )
