"""CLI demo — one ask, full orchestration, no model key needed.

    python -m examples.run_super "Research note-taking methods and build me a one-page guide"
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from core.orchestrator import Ctx, ask
from core.workspace import list_files


async def main(prompt: str) -> None:
    ctx = Ctx(user_id="alice", workspace=Path(tempfile.mkdtemp()) / "ws")
    ctx.memory.approve_fact("alice", "style", "direct and concrete", approved_by="alice")
    result = await ask(prompt, ctx)
    for s in result.steps:
        print(f"[{s.agent}:{s.kind}] {s.task} -> {s.output}")
    print("\nSummary:", result.summary)
    print("Changed files:", result.changed_files)
    print("Workspace:", list_files(ctx.workspace))
    print("Trace:", [e["kind"] for e in ctx.trace.events(ctx.trace_id)])


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or "Research deep work and draft a short guide"))
