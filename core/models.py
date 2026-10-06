"""Model selection — the ONLY model integration point in the system.

Every agent (planner, subagents, reviewer) is built from get_model().
Set SUPER_MODEL (or WORKPLACE_MODEL) to any Pydantic AI model string and
supply that provider's standard credentials in the environment. Nothing
else in the codebase names a model.
"""
from __future__ import annotations

import os


def get_model() -> str:
    return (os.environ.get("SUPER_MODEL")
            or os.environ.get("WORKPLACE_MODEL")
            or "test")  # Pydantic AI TestModel — pipeline runs, content is placeholder
