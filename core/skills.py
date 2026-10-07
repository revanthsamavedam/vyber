"""Skills: git-versioned SKILL.md playbooks. The catalog (name +
description) is cheap and goes in prompts; bodies load on demand."""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class Skill(BaseModel):
    name: str
    description: str
    path: Path

    def body(self) -> str:
        text = self.path.read_text(encoding="utf-8")
        return text.split("---", 2)[-1].strip() if text.startswith("---") else text


def discover(skills_dir: str | Path) -> list[Skill]:
    out = []
    for md in sorted(Path(skills_dir).glob("*/SKILL.md")):
        name, desc = md.parent.name, ""
        text = md.read_text(encoding="utf-8")
        if text.startswith("---"):
            for line in text.split("---", 2)[1].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    if k.strip() == "name":
                        name = v.strip()
                    elif k.strip() == "description":
                        desc = v.strip()
        out.append(Skill(name=name, description=desc, path=md))
    return out


def catalog(skills: list[Skill]) -> str:
    return "\n".join(f"- {s.name}: {s.description}" for s in skills)
