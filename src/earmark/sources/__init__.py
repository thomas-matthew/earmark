"""Saved-item sources (S1-S4). See `base` for the interface each module implements."""
from types import ModuleType

from . import hn, reddit, substack, x
from .base import Context

ALL: list[ModuleType] = [x, reddit, substack, hn]
BY_NAME = {module.NAME: module for module in ALL}

__all__ = ["ALL", "BY_NAME", "Context"]
