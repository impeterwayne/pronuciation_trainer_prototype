"""Pronunciation trainer backend."""

from .config import bootstrap_espeak

bootstrap_espeak()

__all__ = ["bootstrap_espeak"]
