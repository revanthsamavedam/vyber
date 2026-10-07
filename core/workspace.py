"""Workspace: the only place file plans land.

Plans are validated completely before anything is written: path escapes,
duplicate/conflicting paths, file count, and file size. Individual files
are replaced atomically through a temporary sibling file.
"""
from __future__ import annotations

import os
from pathlib import Path

from core.config import SETTINGS
from core.schemas import FileChange


def _validate_files(root: Path, files: list[FileChange]) -> list[tuple[Path, str, str]]:
    if len(files) > SETTINGS.max_file_changes:
        raise ValueError(
            f"file plan has {len(files)} files; limit is {SETTINGS.max_file_changes}")
    seen: dict[str, str] = {}
    validated: list[tuple[Path, str, str]] = []
    for change in files:
        encoded_bytes = len(change.content.encode("utf-8"))
        if encoded_bytes > SETTINGS.max_file_bytes:
            raise ValueError(
                f"file plan exceeds size limit: {change.path} "
                f"({encoded_bytes} > {SETTINGS.max_file_bytes} bytes)")
        target = (root / change.path).resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"plan escapes workspace: {change.path}")
        relative = str(target.relative_to(root))
        if relative in seen and seen[relative] != change.content:
            raise ValueError(f"conflicting duplicate path in file plan: {change.path}")
        if relative not in seen:
            seen[relative] = change.content
            validated.append((target, relative, change.content))
    return validated


def apply_changes(workspace: str | Path, files: list[FileChange]) -> list[str]:
    root = Path(workspace).resolve()
    root.mkdir(parents=True, exist_ok=True)
    validated = _validate_files(root, files)
    changed = []
    for target, relative, content in validated:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.vyber-tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, target)
        changed.append(relative)
    return changed


def list_files(workspace: str | Path) -> list[str]:
    root = Path(workspace)
    if not root.exists():
        return []
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
