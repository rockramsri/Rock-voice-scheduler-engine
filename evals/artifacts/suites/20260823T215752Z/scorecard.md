# Eval scorecard — 20260823T215752Z

5 simulated scenarios, 1 regressions caught before merge, zero hallucinated verdicts (judge-oracle agreement 93.3%, pass^5 on 4/5).

git `8bdb265` · engine `cascade`

| scenario | channel | verdict | pass^k | turns | ttfa p50 | judge Δ | stability |
|---|---|---|---|---|---|---|---|
| co-0001-top-pick-accepts | voice | CONFIRMED_CORRECT | 5/5 ✓ | 2.0 | 894.2ms | 100.0% | stable |
| co-0002-no-weekends-decline | voice | CONFIRMED_CORRECT | 5/5 ✓ | 2.0 | 931.2ms | 0.0% | UNSTABLE |
| co-0003-hard-no-escalates | voice | CONFIRMED_CORRECT | 5/5 ✓ | 1.6 | 1286.8ms | 80.0% | UNSTABLE |
| co-0006-sms-one-shot-accept | sms | CONFIRMED_CORRECT | 5/5 ✓ | 1.0 | 242.6ms | 100.0% | stable |
| co-0014-chatty-no-intent | voice | REGRESSION | 4/5 ✗ | 3.6 | 920.7ms | 80.0% | stable |

## UNSTABLE (excluded from judge average)

- `co-0002-no-weekends-decline`: judge Δ 0.0%
- `co-0003-hard-no-escalates`: judge Δ 80.0%

## All metrics

### co-0001-top-pick-accepts  ·  voice  ·  `cascade`

| metric | role | value |
|---|---|---|
| oracle_verdict | gate | CONFIRMED_CORRECT |
| pass_k | gate | True |
| k | track | 5 |
| passes | track | 5 |
| ttfa_p50_ms | track | 894.2ms |
| full_turn_p95_ms | track | 1621.8ms |
| turns_used | track | 2 |
| judge_oracle_agreement | track | 100.0% |
| judge_stability | track | stable |
| memory_compiled | track | MISSING |
| audit_completeness | track | pass |
| human_fallback | track | skip |
| no_context_bleed | track | pass |
| no_double_text | track | pass |
| quiet_hours | track | skip |
| ranking_first_contact | track | pass |
| scope_two_tools | gate | pass |
| single_winner_lock | gate | pass |
| turn_budget_endstate | track | pass |

### co-0002-no-weekends-decline  ·  voice  ·  `cascade`

| metric | role | value |
|---|---|---|
| oracle_verdict | gate | CONFIRMED_CORRECT |
| pass_k | gate | True |
| k | track | 5 |
| passes | track | 5 |
| ttfa_p50_ms | track | 931.2ms |
| full_turn_p95_ms | track | 1671.0ms |
| turns_used | track | 2 |
| judge_oracle_agreement | track | 0.0% |
| judge_stability | track | UNSTABLE |
| memory_compiled | gate | True |
| audit_completeness | track | pass |
| human_fallback | track | skip |
| no_context_bleed | track | pass |
| no_double_text | track | pass |
| quiet_hours | track | skip |
| ranking_first_contact | track | pass |
| scope_two_tools | gate | pass |
| single_winner_lock | track | skip |
| turn_budget_endstate | track | pass |

### co-0003-hard-no-escalates  ·  voice  ·  `cascade`

| metric | role | value |
|---|---|---|
| oracle_verdict | gate | CONFIRMED_CORRECT |
| pass_k | gate | True |
| k | track | 5 |
| passes | track | 5 |
| ttfa_p50_ms | track | 1286.8ms |
| full_turn_p95_ms | track | 2109.6ms |
| turns_used | track | 1.6 |
| judge_oracle_agreement | track | 80.0% |
| judge_stability | track | UNSTABLE |
| memory_compiled | track | MISSING |
| audit_completeness | track | pass |
| human_fallback | gate | pass |
| no_context_bleed | track | pass |
| no_double_text | track | pass |
| quiet_hours | track | skip |
| ranking_first_contact | track | pass |
| scope_two_tools | gate | pass |
| single_winner_lock | track | skip |
| turn_budget_endstate | track | pass |

### co-0006-sms-one-shot-accept  ·  sms  ·  `cascade`

| metric | role | value |
|---|---|---|
| oracle_verdict | gate | CONFIRMED_CORRECT |
| pass_k | gate | True |
| k | track | 5 |
| passes | track | 5 |
| ttfa_p50_ms | track | 242.6ms |
| full_turn_p95_ms | track | 252.5ms |
| turns_used | track | 1 |
| judge_oracle_agreement | track | 100.0% |
| judge_stability | track | stable |
| memory_compiled | track | MISSING |
| audit_completeness | track | pass |
| human_fallback | track | skip |
| no_context_bleed | track | pass |
| no_double_text | track | pass |
| quiet_hours | track | skip |
| ranking_first_contact | track | pass |
| scope_two_tools | track | pass |
| single_winner_lock | track | pass |
| turn_budget_endstate | track | pass |

### co-0014-chatty-no-intent  ·  voice  ·  `cascade`

| metric | role | value |
|---|---|---|
| oracle_verdict | gate | REGRESSION |
| pass_k | gate | False |
| k | track | 5 |
| passes | track | 4 |
| ttfa_p50_ms | track | 920.7ms |
| full_turn_p95_ms | track | 1941.8ms |
| turns_used | track | 3.6 |
| judge_oracle_agreement | track | 80.0% |
| judge_stability | track | stable |
| memory_compiled | track | MISSING |
| audit_completeness | track | pass |
| human_fallback | track | skip |
| no_context_bleed | track | pass |
| no_double_text | track | pass |
| quiet_hours | track | skip |
| ranking_first_contact | track | pass |
| scope_two_tools | gate | pass |
| single_winner_lock | track | skip |
| turn_budget_endstate | track | fail |

