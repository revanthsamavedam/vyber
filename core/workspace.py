"""Workspace: the only place file plans land. Path escapes are refused —
a plan can never write outside its session workspace."""
from __future__ import annotations

from pathlib import Path

from core.schemas import FileChange


def apply_changes(workspace: str | Path, files: list[FileChange]) -> list[str]:
    root = Path(workspace).resolve()
    root.mkdir(parents=True, exist_ok=True)
    changed = []
    for change in files:
        target = (root / change.path).resolve()
        if not str(target).startswith(str(root)):
            raise ValueError(f"plan escapes workspace: {change.path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(change.content, encoding="utf-8")
        changed.append(change.path)
    return changed


def list_files(workspace: str | Path) -> list[str]:
    root = Path(workspace)
    if not root.exists():
        return []
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
