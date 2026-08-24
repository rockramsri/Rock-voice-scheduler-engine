# Eval scorecard — 20260823T214824Z

5 simulated scenarios, 0 regressions caught before merge, zero hallucinated verdicts (judge-oracle agreement 76.0%, pass^5 on 4/5).

git `8bdb265` · engine `cascade`

| scenario | channel | verdict | pass^k | turns | ttfa p50 | judge Δ | stability |
|---|---|---|---|---|---|---|---|
| co-0006-sms-one-shot-accept | sms | CONFIRMED_CORRECT | 5/5 ✓ | 1.0 | 246.1ms | 100.0% | stable |
| co-0001-top-pick-accepts | voice | CONFIRMED_CORRECT | 5/5 ✓ | 2.0 | 946.9ms | 100.0% | stable |
| co-0002-no-weekends-decline | voice | CONFIRMED_CORRECT | 5/5 ✓ | 2.0 | 908.9ms | 0.0% | UNSTABLE |
| co-0003-hard-no-escalates | voice | CONFIRMED_CORRECT | 5/5 ✓ | 1.8 | 981.1ms | 100.0% | stable |
| co-0014-chatty-no-intent | voice | CONFIRMED_CORRECT | 4/5 ✗ | 3.0 | 999.2ms | 80.0% | stable |
