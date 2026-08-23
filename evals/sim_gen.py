"""scenario.yaml → LiveKit scenarios.yaml (the five fields the proto accepts).

k trials become k copies with distinct run_idx in userdata so parallel cloud
sims seed their own namespaced worlds. No LiveKit Python dispatch API in
1.6.7 — the CLI is the runner.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from evals.contracts import Scenario
from evals.seed import ARTIFACTS_DIR


def to_lk_entry(scenario: Scenario, run_idx: int = 0) -> dict:
    persona = scenario.persona or {}
    policy = "\n".join(f"- {rule}" for rule in persona.get("policy", []))
    style = persona.get("style", "cooperative")
    end = scenario.expected_end_state
    goal = (f"You are a home-health nurse on a phone call. Style: {style}.\n"
            f"HARD RULES:\n{policy}")
    expectations = (scenario.model_extra.get("sim") or {}).get("agent_expectations") or (
        f"End state: {end.status if end else 'unspecified'}"
        + (f" filled by {end.winner}" if end and end.winner else "")
    )
    return {
        "label": f"{scenario.scenario_id} run{run_idx}",
        "instructions": goal,
        "agent_expectations": expectations,
        "tags": {"scenario": scenario.scenario_id, "channel": scenario.channel},
        "userdata": {"scenario_id": scenario.scenario_id, "run_idx": run_idx},
    }


def write_lk_yaml(paths: list[Path], k: int | None = None,
                  dest: Path | None = None) -> Path:
    entries = []
    for path in paths:
        scenario = Scenario.load(path)
        trials = k if k is not None else scenario.k_trials
        for i in range(trials):
            entries.append(to_lk_entry(scenario, i))
    dest = dest or (ARTIFACTS_DIR / "lk-scenarios.yaml")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(yaml.safe_dump({"name": "rock-scheduler-evals",
                                    "scenarios": entries}, sort_keys=False))
    return dest
