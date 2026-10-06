# Super Muse — architecture

One agent is a chatbot. Super Muse is a **team with a manager**:

```
user ──► UI (React, separate repo: super-muse-ui) ──► API (this repo) ──► ORCHESTRATOR
                                                    │ plan
                                              planner_agent → RoutePlan
                                                    │ delegate
              ┌──────────────┬──────────────┬───────┴───────┐
          researcher       builder          data          writer
          (Findings)       (FilePlan)       (DataAnswer)  (Draft)
                                                    │ files?
                                              reviewer_agent → verdict
                                                 veto │ approved
                                                    ▼
                                          workspace (path-safe apply)
         every step ──► trace log + episodic memory; curated memory is
         human-approved only; consequential actions ──► approval store
```

## Design rules

1. **Typed handoffs only.** Agents exchange Pydantic models (`core/schemas.py`), never prose, wherever a structure exists.
2. **Specialists don't talk to the user.** Only the orchestrator reports. A specialist's whole world is its brief + its output type.
3. **The reviewer builds nothing and approves reluctantly.** File plans are applied only after its verdict. A veto writes nothing and tells the user why.
4. **Plans are suggestions.** Unknown agent names in a plan are normalised, file paths are contained to the workspace, and the validator of the real world (tests, compilers, humans) still gets the final say downstream.
5. **Memory has a gate.** Episodes record themselves; curated facts require a named human approver.
6. **The model is a commodity.** All agents read one env var (`SUPER_MODEL`). Swap providers without touching orchestration, skills, or UI.

## Where it came from

Super Muse unifies the pieces built across its sibling templates:
workplace-muse (agent + memory + approvals + MCP connectors) and
vibe-paved-road (pattern skills + validator + studio). This repo is the
personal, general-purpose edition: same bones, no employer patterns,
built to be pointed at your own work.
