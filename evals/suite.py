"""Bottom-up suite: L1/L2 pytest → SMS → voice L3 → scorecards → gate.

  .venv/bin/python -m evals.suite
  .venv/bin/python -m evals.suite --skip-l2          # skip AgentSession tests
  .venv/bin/python -m evals.suite --voice-k 1        # cheaper voice pass
  .venv/bin/python -m evals.suite --cloud-sim        # also try lk agent simulate
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from evals import seed
from evals.contracts import Scenario
from evals.scorecard import (assemble, diff, gate as gate_exit, git_sha,
                             load_baseline, new_suite_id, write_suite)
from evals.seed import EVALS_DIR, REPO_ROOT

PY = REPO_ROOT / ".venv" / "bin" / "python"
SMS_SCENARIOS = list((EVALS_DIR / "scenarios").glob("co-0006*.scenario.yaml"))
VOICE_SCENARIOS = sorted((EVALS_DIR / "scenarios").glob("co-000[123]*.scenario.yaml")) + \
    list((EVALS_DIR / "scenarios").glob("co-0014*.scenario.yaml"))


def _pytest(paths: list[str]) -> int:
    cmd = [str(PY), "-m", "pytest", "-c", "evals/pytest.ini", *paths]
    print("+", " ".join(cmd))
    return subprocess.call(cmd, cwd=REPO_ROOT)


async def _run_channel(module: str, paths: list[Path], k: int | None) -> list[tuple[Scenario, list[dict]]]:
    runner = __import__(module, fromlist=["run_scenario"])
    out = []
    for path in paths:
        scenario = Scenario.load(path)
        trials = k if k is not None else scenario.k_trials
        print(f"\n== {scenario.scenario_id}  channel={scenario.channel}  k={trials}")
        results = await runner.run_scenario(path, trials)
        out.append((scenario, results))
    return out


def try_cloud_sim(k: int = 1) -> str:
    """Attempt `lk agent simulate`. Returns the CLI output or 'MISSING: …'."""
    from dotenv import dotenv_values

    from evals.sim_gen import write_lk_yaml

    env = dotenv_values(REPO_ROOT / ".env")
    url, key, secret = env.get("LIVEKIT_URL"), env.get("LIVEKIT_API_KEY"), env.get("LIVEKIT_API_SECRET")
    if not (url and key and secret):
        return "MISSING: LIVEKIT_* not set"
    yaml_path = write_lk_yaml(
        list((EVALS_DIR / "scenarios").glob("co-0001*.scenario.yaml")), k=k)
    cmd = ["lk", "agent", "simulate", "evals/sim_entry.py",
           "--scenarios", str(yaml_path),
           "--concurrency", "1",
           "--url", url, "--api-key", key, "--api-secret", secret]
    print("+ lk agent simulate evals/sim_entry.py --scenarios", yaml_path, "--concurrency 1")
    try:
        proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        return "MISSING: lk CLI not on PATH"
    except subprocess.TimeoutExpired:
        return "MISSING: lk agent simulate timed out"
    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        # Don't leak keys if the CLI echoed the command line.
        return f"MISSING: lk simulate exit {proc.returncode}: {blob[-800:]}"
    return blob[-800:]


def main() -> int:
    seed.load_eval_env()
    skip_l2 = "--skip-l2" in sys.argv
    cloud = "--cloud-sim" in sys.argv
    voice_k = None
    if "--voice-k" in sys.argv:
        voice_k = int(sys.argv[sys.argv.index("--voice-k") + 1])
    sms_k = None
    if "--sms-k" in sys.argv:
        sms_k = int(sys.argv[sys.argv.index("--sms-k") + 1])

    rc = _pytest(["evals/tests/test_l1_ladder.py",
                  "evals/tests/test_l1_scoring.py",
                  "evals/tests/test_l1_db_guards.py",
                  "evals/tests/test_oracle.py",
                  "evals/tests/test_scorecard.py"])
    if rc != 0:
        print("L1/oracle/scorecard failed — stopping.")
        return rc
    if not skip_l2:
        rc = _pytest(["evals/tests/test_l2_offer_agent.py"])
        if rc != 0:
            print("L2 failed — stopping.")
            return rc

    suite_id = new_suite_id()
    sha = git_sha()
    cards = []

    sms = asyncio.run(_run_channel("evals.run_sms", SMS_SCENARIOS, sms_k))
    voice = asyncio.run(_run_channel("evals.run_voice", VOICE_SCENARIOS, voice_k))
    for scenario, results in sms + voice:
        cards.append(assemble(scenario, results, suite_run_id=suite_id, git=sha))

    folder = write_suite(cards)
    print("\n" + (EVALS_DIR / "scorecard.md").read_text())
    print(f"wrote {folder}")

    blocking = 0
    for card in cards:
        prior = load_baseline(card.scenario_id)
        if prior:
            blocking = max(blocking, gate_exit(diff(card, prior)))
    if blocking:
        print("GATE: a baseline gate metric worsened.")
        return 1

    if cloud:
        print("\n== cloud sim (lk agent simulate)")
        print(try_cloud_sim(k=1))
    else:
        print("cloud sim: MISSING (pass --cloud-sim to attempt; needs lk project creds)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
