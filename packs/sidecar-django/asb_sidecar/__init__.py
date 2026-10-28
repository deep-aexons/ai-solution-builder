"""Sidecar pack entry point: generation and verification."""

from .generate import generate
from .verify import verify

__all__ = ["generate", "verify"]
