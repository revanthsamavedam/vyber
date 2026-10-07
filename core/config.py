"""Runtime limits and timeouts.

Production systems need explicit bounds: an unbounded planner, file plan,
message, or queue is a cost and denial-of-service problem. Every value can
be overridden by environment variable, and the defaults are deliberately
small enough for a single-user/small-team deployment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        return default
    return value if value > 0 else default


def _float_env(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class Settings:
    agent_timeout_seconds: float = 120.0
    max_tasks_per_plan: int = 8
    max_file_changes: int = 50
    max_file_bytes: int = 256_000
    max_message_chars: int = 20_000
    max_queued_runs_per_session: int = 20
    max_context_chars_per_dependency: int = 12_000

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            agent_timeout_seconds=_float_env(
                "VYBER_AGENT_TIMEOUT_SECONDS", cls.agent_timeout_seconds),
            max_tasks_per_plan=_int_env(
                "VYBER_MAX_TASKS_PER_PLAN", cls.max_tasks_per_plan),
            max_file_changes=_int_env(
                "VYBER_MAX_FILE_CHANGES", cls.max_file_changes),
            max_file_bytes=_int_env(
                "VYBER_MAX_FILE_BYTES", cls.max_file_bytes),
            max_message_chars=_int_env(
                "VYBER_MAX_MESSAGE_CHARS", cls.max_message_chars),
            max_queued_runs_per_session=_int_env(
                "VYBER_MAX_QUEUED_RUNS_PER_SESSION",
                cls.max_queued_runs_per_session),
            max_context_chars_per_dependency=_int_env(
                "VYBER_MAX_CONTEXT_CHARS_PER_DEPENDENCY",
                cls.max_context_chars_per_dependency),
        )


SETTINGS = Settings.from_env()
