"""Scorecard assemble / diff / gate — pure, no network, no DB."""

from evals.contracts import EndState, Scenario
from evals.scorecard import (CATALOG, Metric, Scorecard, assemble, compare,
                             diff, gate, render)


def _scenario(**over) -> Scenario:
    data = dict(scenario_id="co-test", channel="sms",
                expected_end_state=EndState(shift="SH-1", status="filled", winner="CG-101"),
                gates=["oracle_verdict", "single_winner_lock"],
                k_trials=5, seed=1)
    data.update(over)
    return Scenario(**data)


def _run(verdict="CONFIRMED_CORRECT", **over) -> dict:
    row = dict(run_idx=0, verdict=verdict,
               checks={"single_winner_lock": "pass", "no_double_text": "pass"},
               judge_all_yes=True, judge_model="anthropic:claude-sonnet-4-6",
               turns=1, ttfa_ms=300.0, per_turn_ms=[300.0], artifacts=None)
    row.update(over)
    return row


def test_assemble_pass_k_and_percentiles():
    runs = [_run(run_idx=i, ttfa_ms=100.0 * (i + 1), per_turn_ms=[100.0 * (i + 1)])
            for i in range(5)]
    card = assemble(_scenario(), runs, suite_run_id="T")
    assert card.nondeterministic["pass_k"] is True
    assert card.nondeterministic["k"] == 5
    assert card.metric("ttfa_p50_ms").value == 300.0
    assert card.metric("oracle_verdict").value == "CONFIRMED_CORRECT"
    assert card.metric("single_winner_lock").role == "gate"
    assert card.metric("no_double_text").role == "track"   # not in gates


def test_assemble_regression_when_one_trial_fails():
    runs = [_run(run_idx=i) for i in range(4)]
    runs.append(_run(run_idx=4, verdict="REGRESSION",
                     checks={"single_winner_lock": "fail"}))
    card = assemble(_scenario(), runs, suite_run_id="T")
    assert card.nondeterministic["pass_k"] is False
    assert card.deterministic["oracle_verdict"] == "REGRESSION"
    assert card.evidence["failing_run_idx"] == 4
    assert card.metric("single_winner_lock").value == "fail"


def test_diff_gate_worsening_blocks():
    good = Scorecard(scenario_id="x", suite_run_id="a", metrics=[
        Metric(name="oracle_verdict", role="gate", value="CONFIRMED_CORRECT"),
        Metric(name="ttfa_p50_ms", role="track", value=200.0, unit="ms"),
    ])
    bad = Scorecard(scenario_id="x", suite_run_id="b", metrics=[
        Metric(name="oracle_verdict", role="gate", value="REGRESSION"),
        Metric(name="ttfa_p50_ms", role="track", value=800.0, unit="ms"),
    ])
    deltas = diff(bad, good)
    assert any(d.name == "oracle_verdict" and d.blocks for d in deltas)
    assert any(d.name == "ttfa_p50_ms" and d.direction == "worse" and not d.blocks
               for d in deltas)
    assert gate(deltas) == 1


def test_diff_same_does_not_block():
    a = Scorecard(scenario_id="x", suite_run_id="a", metrics=[
        Metric(name="oracle_verdict", role="gate", value="CONFIRMED_CORRECT")])
    assert gate(diff(a, a)) == 0


def test_compare_never_blocks():
    cascade = Scorecard(scenario_id="x", suite_run_id="a", engine_profile="cascade",
                        metrics=[Metric(name="ttfa_p50_ms", role="track", value=200.0)])
    realtime = Scorecard(scenario_id="x", suite_run_id="a", engine_profile="realtime",
                         metrics=[Metric(name="ttfa_p50_ms", role="track", value=80.0)])
    deltas = compare(cascade, realtime)
    assert all(d.role == "compare" and not d.blocks for d in deltas)
    assert deltas[0].direction == "better"   # 80 < 200, latency


def test_missing_stays_missing():
    card = assemble(_scenario(), [_run(ttfa_ms=None, per_turn_ms=[])], suite_run_id="T")
    assert card.metric("ttfa_p50_ms").value is None
    assert card.metric("ttfa_p50_ms").as_text() == "MISSING"
    md = render([card])
    assert "MISSING" in md


def test_catalog_is_the_compare_contract():
    """Every assembled number has a catalog name; later benches use the same keys."""
    assert "oracle_verdict" in CATALOG
    assert CATALOG["ttfa_p50_ms"].higher_is_worse
    card = assemble(_scenario(), [_run()], suite_run_id="T")
    named = {m.name for m in card.metrics}
    for core in ("oracle_verdict", "pass_k", "k", "passes",
                 "ttfa_p50_ms", "full_turn_p95_ms", "turns_used",
                 "judge_oracle_agreement", "judge_stability"):
        assert core in named
        assert core in CATALOG
    md = render([card])
    assert "## All metrics" in md
    assert "| oracle_verdict | gate |" in md


def test_render_excludes_unstable_from_headline_average():
    stable = assemble(_scenario(scenario_id="ok"), [_run()], suite_run_id="T")
    flips = [_run(run_idx=i, judge_all_yes=(i == 0)) for i in range(5)]
    unstable = assemble(_scenario(scenario_id="flaky"), flips, suite_run_id="T")
    assert unstable.metric("judge_stability").value == "UNSTABLE"
    md = render([stable, unstable])
    assert "judge-oracle agreement 100.0%" in md
    assert "## UNSTABLE" in md
    assert "`flaky`" in md
