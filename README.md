# super-muse

A multi-agent personal work agent on **Pydantic AI**. You make one request;
a planner splits it, specialist subagents do the parts, a reviewer gates
anything that would be written, and you see the whole trace.

Read **[ARCHITECTURE.md](ARCHITECTURE.md)** for the design.

## The team

| Agent | Brief | Output |
|---|---|---|
| planner | Split the request into subtasks | `RoutePlan` |
| researcher | Investigate, facts vs inference | `Findings` |
| builder | Create/change files, complete contents | `FilePlan` |
| data | Answer from governed sources, with freshness | `DataAnswer` |
| writer | Finished drafts — never sends | `Draft` |
| reviewer | Judge plans/drafts, veto power, builds nothing | `ReviewVerdict` |

Plus the machinery that makes it trustworthy: 3-tier memory (curated =
human-approved only), an approval store for consequential actions, an
append-only trace, git-versioned `SKILL.md` skills, and a path-safe
workspace that file plans can't escape.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
python -m examples.run_super "Research deep work and build me a one-page guide"
uvicorn api.main:app --port 8091        # backend API (this repo)
```

**UI is a separate repo:** [super-muse-ui](https://github.com/revanthsamavedam/super-muse-ui) (React + Vite). Clone it, `npm install && npm run dev`, and it talks to this API on :8091 (CORS preconfigured for the Vite ports; override with `SUPER_CORS_ORIGINS`).

**Chat is non-blocking:** `POST /api/chat` returns `202 {run_id}` immediately. Runs execute in the background — one at a time per session (a session's workspace is never written by two runs at once), extra messages queue. Watch a run live via `GET /api/runs/{id}/events` (SSE: status / subagent.started / step / result), poll `GET /api/runs/{id}`, or stop it with `POST /api/runs/{id}/cancel` (queued runs never start; a running run cancels at its next await point).

## The model is yours to plug in

Everything runs with **no key** on Pydantic AI's TestModel — full pipeline,
placeholder content. Set one variable to make it real:

```bash
SUPER_MODEL="openai:gpt-5" uvicorn api.main:app --port 8091
# any Pydantic AI model string works: azure:, anthropic:, your gateway…
```

That env var (`core/models.py`) is the entire model integration — every
agent in the system reads it, nothing else names a model.
