# Vyber production readiness

Vyber's application code is built to production standards for a
single-instance deployment: typed routing, bounded work, ownership
checks, persistent runs, deterministic safety gates, readiness probes,
and restart recovery.

It is **not** yet a multi-instance or public-internet production system.
The remaining items below are deployment and identity work, not hidden
application features.

## Implemented

- **Routing:** typed agent names; validated task DAG; explicit upstream
  context; parallel execution of independent tasks; one bounded reviewer
  revision; routing defects recorded on every result.
- **Safety:** path-safe atomic file application; duplicate-path conflict
  detection; deterministic credential scan before reviewer/apply;
  reviewer veto; per-file and per-plan limits.
- **Ownership:** sessions and runs belong to the authenticated caller.
  Another caller receives 404, not another user's data.
- **Reliability:** SQLite WAL + busy timeout (Postgres by URL); runs and
  events persist; interrupted runs are marked failed on restart; queued
  runs are bounded per session; agent calls have timeouts.
- **Operations:** `/healthz` liveness, `/readyz` database + workspace
  readiness, `X-Request-ID` correlation, structured request logs,
  generic 500 responses that do not leak exception details.
- **Evaluation:** `evals/routing_cases.json` (18 cases) and
  `python -m evals.run_routing_evals --repeat 3` for planner changes.
- **UI recovery:** the browser restores its session, prior runs, files,
  and review state; if SSE drops, it falls back to polling.

## Required before real users

1. **Switch auth to JWT mode.** Demo mode is a development stub. The
   seam is built (`api/auth.py`): set `VYBER_AUTH_MODE=jwt` with the
   JWKS URL, issuer, and audience of your IdP or JWT authorization
   service (plus `VYBER_JWT_USER_CLAIM` if the caller id is not in
   `sub`). The caller's token is threaded to the run context for
   on-behalf-of tool/MCP calls; it is never persisted.
2. **Configure the real model and pass evals.** Set `VYBER_MODEL` to the
   Azure OpenAI deployment, run the routing suite repeatedly, and review
   failures before release. TestModel results do not measure judgment.
3. **Terminate TLS** at Caddy, an ALB, or CloudFront. Do not expose the
   demo-auth API directly to the internet.
4. **Smoke-test the Docker stack on the target EC2 host.** The compose
   files are validated and the services are tested outside containers;
   the target host is where image builds must be proven.
5. **Back up the data directory / database.** On the single-box deploy,
   `~/vyber-data` is the product state. Snapshot it with EBS or use RDS.
6. **Decide data retention.** Runs, events, traces, and episodic memory
   accumulate by design. Set a retention policy for the deployment.

## Known scaling boundary

The run queue and SSE subscribers live in one API process. Run exactly
one API instance. Horizontal scale requires moving the queue to SQS (or
equivalent), run events to a pub/sub channel, and workspace execution to
isolated runner tasks. The database and file-workspace boundaries were
designed so that is an infrastructure change, not an agent rewrite.
