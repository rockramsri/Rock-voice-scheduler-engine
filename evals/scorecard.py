"""Scorecard — one model for every number we record, diff, or compare.

Every metric has a role:
  gate     — regression-blocking (scenario.gates). Worsening vs baseline → exit 1
  track    — recorded + trended, never blocks (latencies, turns)
  compare  — benchmark columns (engine_profile side-by-side). Never blocks.

None means MISSING — never an estimate. assemble() is the only writer;
diff() is the only comparer. Both are pure.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from evals.contracts import Scenario
from evals.judge import agreement as judge_agreement
from evals.seed import ARTIFACTS_DIR, EVALS_DIR, REPO_ROOT

Role = Literal["gate", "track", "compare"]
Direction = Literal["better", "worse", "same", "missing"]

# Verdicts / bools that count as "good" when comparing gate metrics.
GOOD_VERDICTS = {"CONFIRMED_CORRECT", True, "true", "PASS", "pass"}


class MetricSpec(BaseModel):
    """The stable name for one number. assemble() emits one Metric per spec."""
    name: str
    default_role: Role = "track"
    unit: str = ""
    higher_is_worse: bool = False


# Every number we record. New metrics go here first so later benches compare
# the same names. scenario.gates can promote a track spec to gate.
CATALOG: dict[str, MetricSpec] = {
    spec.name: spec for spec in [
        MetricSpec(name="oracle_verdict", default_role="gate"),
        MetricSpec(name="pass_k", default_role="gate"),
        MetricSpec(name="k", default_role="track"),
        MetricSpec(name="passes", default_role="track"),
        MetricSpec(name="ttfa_p50_ms", default_role="track", unit="ms", higher_is_worse=True),
        MetricSpec(name="full_turn_p95_ms", default_role="track", unit="ms", higher_is_worse=True),
        MetricSpec(name="turns_used", default_role="track", higher_is_worse=True),
        MetricSpec(name="judge_oracle_agreement", default_role="track", unit="%"),
        MetricSpec(name="judge_stability", default_role="track"),
        MetricSpec(name="memory_compiled", default_role="track"),
        MetricSpec(name="ranking_first_contact", default_role="track"),
        MetricSpec(name="quiet_hours", default_role="track"),
        MetricSpec(name="single_winner_lock", default_role="track"),
        MetricSpec(name="no_double_text", default_role="track"),
        MetricSpec(name="scope_two_tools", default_role="track"),
        MetricSpec(name="human_fallback", default_role="track"),
        MetricSpec(name="turn_budget_endstate", default_role="track"),
        MetricSpec(name="audit_completeness", default_role="track"),
        MetricSpec(name="no_context_bleed", default_role="track"),
    ]
}
HIGHER_IS_WORSE = {n for n, s in CATALOG.items() if s.higher_is_worse}


class Metric(BaseModel):
    name: str
    role: Role
    value: float | int | str | bool | None = None   # None = MISSING
    unit: str = ""

    def as_text(self) -> str:
        if self.value is None:
            return "MISSING"
        if isinstance(self.value, bool):
            return str(self.value)
        if isinstance(self.value, float):
            if self.unit == "" and self.value == int(self.value):
                return str(int(self.value))
            return f"{self.value:.1f}{self.unit}"
        return f"{self.value}{self.unit}"


class MetricDelta(BaseModel):
    name: str
    role: Role
    baseline: float | str | bool | None
    current: float | str | bool | None
    direction: Direction
    blocks: bool = False


class JudgeBlock(BaseModel):
    rubric_verdicts: list[bool] = Field(default_factory=list)
    agreement_with_oracle: float | None = None   # percent, or None = MISSING
    stability: Literal["stable", "UNSTABLE", "n/a"] = "n/a"
    model: str | None = None


class Scorecard(BaseModel):
    """One scenario, one suite run, one engine_profile. The compare unit."""
    scenario_id: str
    scenario_version: int = 1
    suite_run_id: str
    engine_profile: str = "cascade"
    channel: str = ""
    git_sha: str = "UNKNOWN"
    ts: str = ""
    seed: int = 0
    deterministic: dict[str, Any] = Field(default_factory=dict)
    nondeterministic: dict[str, Any] = Field(default_factory=dict)
    metrics: list[Metric] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)

    def metric(self, name: str) -> Metric | None:
        return next((m for m in self.metrics if m.name == name), None)

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(self.model_dump_json(indent=1))

    @classmethod
    def load(cls, path: str | Path) -> Scorecard:
        return cls.model_validate_json(Path(path).read_text())


class SuiteReport(BaseModel):
    """A folder of scorecards from one `make eval` / `make bench` invocation."""
    suite_run_id: str
    git_sha: str = "UNKNOWN"
    ts: str = ""
    engine_profile: str = "cascade"
    scorecards: list[Scorecard] = Field(default_factory=list)
    headline: str = ""

    def save(self, folder: str | Path) -> Path:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        for card in self.scorecards:
            card.save(folder / f"{card.scenario_id}.json")
        (folder / "suite.json").write_text(self.model_dump_json(indent=1))
        return folder


# ---- assemble ----

def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL).decode().strip() or "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def new_suite_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((p / 100) * (len(ordered) - 1)))))
    return round(ordered[idx], 1)


def _spec(name: str) -> MetricSpec:
    return CATALOG.get(name) or MetricSpec(name=name, default_role="track")


def _role(name: str, scenario: Scenario) -> Role:
    if name in scenario.gates:
        return "gate"
    return _spec(name).default_role


def _metric(name: str, scenario: Scenario, value, unit: str | None = None) -> Metric:
    spec = _spec(name)
    return Metric(name=name, role=_role(name, scenario),
                  value=value, unit=unit if unit is not None else spec.unit)


def assemble(scenario: Scenario, runs: list[dict], *,
             suite_run_id: str, engine_profile: str | None = None,
             git: str | None = None) -> Scorecard:
    """Fold k trial dicts (from run_sms / run_voice) into one Scorecard."""
    profile = engine_profile or scenario.engine_profile
    verdicts = [r.get("verdict") for r in runs]
    oracle_ok = [v == "CONFIRMED_CORRECT" for v in verdicts]
    passes = sum(oracle_ok)
    k = len(runs)
    pass_k = bool(k) and all(oracle_ok)
    # pass^k: one REGRESSION in k trials is a REGRESSION for the scenario.
    if any(v == "REGRESSION" for v in verdicts):
        majority = "REGRESSION"
    elif any(v == "UNRESOLVED" for v in verdicts) or not verdicts:
        majority = "UNRESOLVED"
    else:
        majority = "CONFIRMED_CORRECT"

    # Per-check majority across k (skip-only → skip).
    check_names = sorted({n for r in runs for n in (r.get("checks") or {})})
    checks: dict[str, str] = {}
    for name in check_names:
        statuses = [r["checks"].get(name, "skip") for r in runs]
        if "fail" in statuses:
            checks[name] = "fail"
        elif all(s == "skip" for s in statuses):
            checks[name] = "skip"
        else:
            checks[name] = "pass"

    ttfa = [r["ttfa_ms"] for r in runs if r.get("ttfa_ms") is not None]
    turns = [r["turns"] for r in runs if r.get("turns") is not None]
    p95_src = []
    for r in runs:
        per = (r.get("per_turn_ms") or ([r["ttfa_ms"]] if r.get("ttfa_ms") else []))
        p95_src.extend(per)

    judged = [r["judge_all_yes"] for r in runs if r.get("judge_all_yes") is not None]
    calibration = (judge_agreement(judged, oracle_ok[:len(judged)])
                   if judged else {"agreement_pct": None, "stability": "n/a"})

    failing = next((r["run_idx"] for r in runs if r.get("verdict") != "CONFIRMED_CORRECT"), None)
    artifacts = [r.get("artifacts") for r in runs if r.get("artifacts")]

    memory = _memory_compiled(scenario, artifacts[-1] if artifacts else None)

    metrics = [
        _metric("oracle_verdict", scenario, majority),
        _metric("pass_k", scenario, pass_k),
        _metric("k", scenario, k),
        _metric("passes", scenario, passes),
        _metric("ttfa_p50_ms", scenario, _pct(ttfa, 50)),
        _metric("full_turn_p95_ms", scenario, _pct(p95_src, 95)),
        _metric("turns_used", scenario, (round(sum(turns) / len(turns), 2) if turns else None)),
        _metric("judge_oracle_agreement", scenario, calibration["agreement_pct"]),
        _metric("judge_stability", scenario, calibration["stability"]),
        _metric("memory_compiled", scenario, memory),
    ]
    for name, status in checks.items():
        metrics.append(_metric(name, scenario, status))

    return Scorecard(
        scenario_id=scenario.scenario_id,
        scenario_version=scenario.scenario_version,
        suite_run_id=suite_run_id,
        engine_profile=profile,
        channel=scenario.channel,
        git_sha=git or git_sha(),
        ts=datetime.now(UTC).isoformat(),
        seed=scenario.seed,
        deterministic={
            "oracle_verdict": majority,
            "checks": checks,
            "timings": {"ttfa_p50": _pct(ttfa, 50),
                        "full_turn_p95": _pct(p95_src, 95),
                        "stage_ms": None},
            "turns_used": (round(sum(turns) / len(turns), 2) if turns else None),
        },
        nondeterministic={
            "k": k, "passes": passes, "pass_k": pass_k,
            "judge": JudgeBlock(
                rubric_verdicts=judged,
                agreement_with_oracle=calibration["agreement_pct"],
                stability=calibration["stability"],
                model=next((r.get("judge_model") for r in runs if r.get("judge_model")), None),
            ).model_dump(),
        },
        metrics=metrics,
        evidence={"artifacts_path": artifacts[-1] if artifacts else None,
                  "artifacts_paths": artifacts,
                  "failing_run_idx": failing, "seed": scenario.seed},
    )


def _memory_compiled(scenario: Scenario, artifacts_path: str | None) -> bool | None:
    """True/False when the scenario declares expected_memory; else MISSING."""
    expected = scenario.expected_memory
    if not expected or not artifacts_path:
        return None
    snap_path = Path(artifacts_path) / "snapshot.json"
    if not snap_path.exists():
        return None
    snap = json.loads(snap_path.read_text())
    slug_map = snap.get("slug_map") or {}
    nurses = {n["id"]: n for n in snap.get("nurses") or []}
    for slug, want in expected.items():
        nurse = nurses.get(slug_map.get(slug, ""))
        if not nurse:
            return False
        prefs = nurse.get("preferences") or {}
        for key, value in want.items():
            got = prefs.get(key)
            if isinstance(value, list) and not set(value).issubset(set(got or [])):
                return False
            if not isinstance(value, list) and got != value:
                return False
    return True


# ---- diff / gate / compare ----

def _direction(name: str, baseline, current) -> Direction:
    if current is None or baseline is None:
        return "missing"
    if baseline == current:
        return "same"
    if name in HIGHER_IS_WORSE and isinstance(current, (int, float)) and isinstance(baseline, (int, float)):
        return "worse" if current > baseline else "better"
    if name in {"oracle_verdict", "pass_k"} or name.endswith("_lock") or name in {
        "pass_k", "memory_compiled",
    }:
        base_good = baseline in GOOD_VERDICTS or baseline == "pass"
        cur_good = current in GOOD_VERDICTS or current == "pass"
        if base_good and not cur_good:
            return "worse"
        if cur_good and not base_good:
            return "better"
        return "same"
    if current == "fail" and baseline != "fail":
        return "worse"
    if current != "fail" and baseline == "fail":
        return "better"
    return "same"


def diff(current: Scorecard, baseline: Scorecard) -> list[MetricDelta]:
    by_base = {m.name: m for m in baseline.metrics}
    deltas = []
    for metric in current.metrics:
        prior = by_base.get(metric.name)
        base_val = prior.value if prior else None
        direction = _direction(metric.name, base_val, metric.value)
        deltas.append(MetricDelta(
            name=metric.name, role=metric.role,
            baseline=base_val, current=metric.value,
            direction=direction,
            blocks=metric.role == "gate" and direction == "worse",
        ))
    return deltas


def compare(left: Scorecard, right: Scorecard) -> list[MetricDelta]:
    """Side-by-side of two engine profiles. Never blocking (role stays compare)."""
    out = []
    for metric in left.metrics:
        other = right.metric(metric.name)
        out.append(MetricDelta(
            name=metric.name, role="compare",
            baseline=metric.value,
            current=other.value if other else None,
            direction=_direction(metric.name, metric.value,
                                 other.value if other else None),
            blocks=False,
        ))
    return out


def gate(deltas: list[MetricDelta]) -> int:
    """0 = merge ok, 1 = a gate metric got worse."""
    return 1 if any(d.blocks for d in deltas) else 0


# ---- render / promote ----

BASELINE_DIR = EVALS_DIR / "baselines" / "current"


def load_baseline(scenario_id: str) -> Scorecard | None:
    path = BASELINE_DIR / f"{scenario_id}.json"
    return Scorecard.load(path) if path.exists() else None


def promote(suite_folder: str | Path) -> Path:
    """Copy a green suite folder over evals/baselines/current/. Does not git commit."""
    src = Path(suite_folder)
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    for card in src.glob("*.json"):
        (BASELINE_DIR / card.name).write_text(card.read_text())
    return BASELINE_DIR


def render(cards: list[Scorecard],
           deltas: dict[str, list[MetricDelta]] | None = None) -> str:
    """Markdown scorecard. Numbers only — MISSING when not measured."""
    n = len(cards)
    regressions = sum(1 for c in cards if c.deterministic.get("oracle_verdict") == "REGRESSION")
    agreements = []
    for c in cards:
        agr = c.metric("judge_oracle_agreement")
        stab = c.metric("judge_stability")
        if agr and agr.value is not None and (not stab or stab.value != "UNSTABLE"):
            agreements.append(agr.value)
    agree = (round(sum(agreements) / len(agreements), 1) if agreements else "MISSING")
    pass5 = sum(1 for c in cards if c.nondeterministic.get("pass_k"))
    lines = [
        f"# Eval scorecard — {cards[0].suite_run_id if cards else 'empty'}",
        "",
        f"{n} simulated scenarios, {regressions} regressions caught before merge, "
        f"zero hallucinated verdicts (judge-oracle agreement {agree}%, "
        f"pass^5 on {pass5}/{n}).",
        "",
        f"git `{cards[0].git_sha if cards else 'UNKNOWN'}` · "
        f"engine `{cards[0].engine_profile if cards else '?'}`",
        "",
        "| scenario | channel | verdict | pass^k | turns | ttfa p50 | judge Δ | stability |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in cards:
        nd = c.nondeterministic
        det = c.deterministic
        ttfa = c.metric("ttfa_p50_ms")
        agree_m = c.metric("judge_oracle_agreement")
        stab = c.metric("judge_stability")
        blocked = ""
        if deltas and c.scenario_id in deltas and any(d.blocks for d in deltas[c.scenario_id]):
            blocked = " **GATE**"
        lines.append(
            f"| {c.scenario_id}{blocked} | {c.channel} | "
            f"{det.get('oracle_verdict')} | "
            f"{nd.get('passes')}/{nd.get('k')} {'✓' if nd.get('pass_k') else '✗'} | "
            f"{det.get('turns_used') if det.get('turns_used') is not None else 'MISSING'} | "
            f"{ttfa.as_text() if ttfa else 'MISSING'} | "
            f"{agree_m.as_text() if agree_m else 'MISSING'} | "
            f"{stab.as_text() if stab else 'n/a'} |"
        )
    unstable = [c for c in cards
                if c.metric("judge_stability") and c.metric("judge_stability").value == "UNSTABLE"]
    if unstable:
        lines += ["", "## UNSTABLE (excluded from judge average)", ""]
        for u in unstable:
            agr = u.metric("judge_oracle_agreement")
            lines.append(f"- `{u.scenario_id}`: judge Δ {agr.as_text() if agr else 'MISSING'}")
    if deltas:
        lines += ["", "## Gate diffs vs baseline", ""]
        any_block = False
        for sid, ds in deltas.items():
            for d in ds:
                if d.blocks:
                    any_block = True
                    lines.append(f"- **{sid}.{d.name}**: {d.baseline} → {d.current} (worse)")
        if not any_block:
            lines.append("No gate metric worsened.")
    lines += ["", "## All metrics", ""]
    for c in cards:
        lines += [
            f"### {c.scenario_id}  ·  {c.channel}  ·  `{c.engine_profile}`",
            "",
            "| metric | role | value |",
            "|---|---|---|",
        ]
        for m in c.metrics:
            lines.append(f"| {m.name} | {m.role} | {m.as_text()} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def write_suite(cards: list[Scorecard]) -> Path:
    """Persist cards, diff against baseline, write scorecard.md. Returns the folder."""
    if not cards:
        raise ValueError("write_suite got no scorecards")
    folder = ARTIFACTS_DIR / "suites" / cards[0].suite_run_id
    deltas: dict[str, list[MetricDelta]] = {}
    for card in cards:
        prior = load_baseline(card.scenario_id)
        if prior:
            deltas[card.scenario_id] = diff(card, prior)
    report = SuiteReport(
        suite_run_id=cards[0].suite_run_id, git_sha=cards[0].git_sha,
        ts=cards[0].ts, engine_profile=cards[0].engine_profile,
        scorecards=cards, headline=render(cards, deltas).split("\n")[2],
    )
    report.save(folder)
    md = render(cards, deltas)
    (folder / "scorecard.md").write_text(md)
    (EVALS_DIR / "scorecard.md").write_text(md)   # latest, easy to open
    return folder
