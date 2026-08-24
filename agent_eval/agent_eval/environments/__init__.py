"""Evaluation environment layer (design doc §6, unified 2026-08-23).

One Env class with pluggable backends (memory / disk / future). Datasets stay
file-isolated; evaluation runs through a single Env interface regardless of domain.
"""

from .base import BaseEnv
from .env import Env
from .tool_env import ToolCallingEnv, ToolError

__all__ = ["BaseEnv", "Env", "ToolCallingEnv", "ToolError"]
