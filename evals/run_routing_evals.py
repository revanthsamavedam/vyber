"""Run the routing eval suite against the configured planner model.

Usage:
    VYBER_MODEL=azure:<deployment> python -m evals.run_routing_evals \
        --repeat 3 --output routing-results.json --fail-under 0.8

With VYBER_MODEL unset this uses Pydantic AI's TestModel. That proves the
harness plumbing only — it says nothing about routing judgment.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.evals import RoutingCase, aggregate, score_plan  # noqa: E402
from core.models import get_model  # noqa: E402
from core.routing import normalize_plan  # noqa: E402
from core.subagents import planner_agent  # noqa: E402


async def run(cases: list[RoutingCase], repeat: int) -> list[dict]:
    results = []
    for iteration in range(repeat):
        for case in cases:
            raw = (await planner_agent.run(
                f"User request: {case.prompt}\nApproved context: ")).output
            plan, defects = normalize_plan(raw, case.prompt)
            result = score_plan(case, plan, defects)
            result["iteration"] = iteration + 1
            results.append(result)
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(Path(__file__).with_name("routing_cases.json")))
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output")
    parser.add_argument("--fail-under", type=float,
                        help="exit non-zero if acceptable-route rate is below this")
    args = parser.parse_args()

    cases = [RoutingCase.from_dict(d)
             for d in json.loads(Path(args.cases).read_text())]
    model = get_model()
    if model == "test":
        print("WARNING: VYBER_MODEL is unset — TestModel results measure "
              "plumbing, not routing quality.", file=sys.stderr)
    results = asyncio.run(run(cases, max(1, args.repeat)))
    summary = aggregate(results)
    payload = {"model": model, "summary": summary, "results": results}
    print(json.dumps(summary, indent=2))
    if args.output:
        Path(args.output).write_text(json.dumps(payload, indent=2))
    if args.fail_under is not None and summary["acceptable_route_rate"] < args.fail_under:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
