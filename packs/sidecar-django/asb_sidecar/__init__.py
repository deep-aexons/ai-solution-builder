"""Sidecar pack entry point; verification arrives in a later task."""

from .generate import generate

__all__ = ["generate", "verify"]


def verify(solution, solution_dir):
    raise NotImplementedError("implemented in a later task")
