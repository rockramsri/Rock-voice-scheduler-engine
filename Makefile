# Rock Scheduler eval harness. Everything runs through the repo venv.
PY := .venv/bin/python

.PHONY: test-l1 test-l2 test-oracle eval eval-one eval-server bench baseline-promote

# API for the ops console's Evals pages (http://localhost:8321, eval DB only).
eval-server:
	$(PY) -m evals.server

test-l1:
	$(PY) -m pytest -c evals/pytest.ini evals/tests/test_l1_ladder.py \
	  evals/tests/test_l1_scoring.py evals/tests/test_l1_db_guards.py

test-oracle:
	$(PY) -m pytest -c evals/pytest.ini evals/tests/test_oracle.py evals/tests/test_scorecard.py

test-l2:
	$(PY) -m pytest -c evals/pytest.ini evals/tests/test_l2_offer_agent.py -v

eval-one:
	$(PY) -m evals.run_sms $(wildcard evals/scenarios/$(ID)*.scenario.yaml) $(if $(K),--k $(K),)

eval:
	$(PY) -m evals.suite $(if $(VOICE_K),--voice-k $(VOICE_K),) $(if $(SMS_K),--sms-k $(SMS_K),)

bench:
	@echo "bench (cascade vs realtime) arrives with M7 — Scorecard.compare() is ready"

baseline-promote:
	$(PY) -c "from evals.scorecard import promote, ARTIFACTS_DIR; \
	  latest=max((ARTIFACTS_DIR/'suites').glob('*')); \
	  print(promote(latest))"
