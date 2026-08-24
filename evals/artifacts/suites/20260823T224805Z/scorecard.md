# Eval scorecard — 20260823T224805Z

5 simulated scenarios, 0 regressions caught before merge, zero hallucinated verdicts (judge-oracle agreement 100.0%, pass^5 on 5/5).

git `8bdb265` · engine `cascade`

| scenario | channel | verdict | pass^k | turns | ttfa p50 | judge Δ | stability |
|---|---|---|---|---|---|---|---|
| co-0006-sms-one-shot-accept | sms | CONFIRMED_CORRECT | 5/5 ✓ | 1.0 | 231.4ms | 100.0% | stable |
| co-0001-top-pick-accepts | voice | CONFIRMED_CORRECT | 5/5 ✓ | 2.0 | 1018.9ms | 100.0% | stable |
| co-0002-no-weekends-decline | voice | CONFIRMED_CORRECT | 5/5 ✓ | 2.0 | 1041.9ms | 100.0% | stable |
| co-0003-hard-no-escalates | voice | CONFIRMED_CORRECT | 5/5 ✓ | 2.0 | 964.8ms | 100.0% | stable |
| co-0014-chatty-no-intent | voice | CONFIRMED_CORRECT | 5/5 ✓ | 3.0 | 900.7ms | 100.0% | stable |

## All metrics

### co-0006-sms-one-shot-accept  ·  sms  ·  `cascade`

| metric | role | value |
|---|---|---|
| oracle_verdict | gate | CONFIRMED_CORRECT |
| pass_k | gate | True |
| k | track | 5 |
| passes | track | 5 |
| ttfa_p50_ms | track | 231.4ms |
| full_turn_p95_ms | track | 248.4ms |
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

### co-0001-top-pick-accepts  ·  voice  ·  `cascade`

| metric | role | value |
|---|---|---|
| oracle_verdict | gate | CONFIRMED_CORRECT |
| pass_k | gate | True |
| k | track | 5 |
| passes | track | 5 |
| ttfa_p50_ms | track | 1018.9ms |
| full_turn_p95_ms | track | 1877.1ms |
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
| ttfa_p50_ms | track | 1041.9ms |
| full_turn_p95_ms | track | 1921.3ms |
| turns_used | track | 2 |
| judge_oracle_agreement | track | 100.0% |
| judge_stability | track | stable |
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
| ttfa_p50_ms | track | 964.8ms |
| full_turn_p95_ms | track | 1595.9ms |
| turns_used | track | 2 |
| judge_oracle_agreement | track | 100.0% |
| judge_stability | track | stable |
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

### co-0014-chatty-no-intent  ·  voice  ·  `cascade`

| metric | role | value |
|---|---|---|
| oracle_verdict | gate | CONFIRMED_CORRECT |
| pass_k | gate | True |
| k | track | 5 |
| passes | track | 5 |
| ttfa_p50_ms | track | 900.7ms |
| full_turn_p95_ms | track | 1676.3ms |
| turns_used | track | 3 |
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
| single_winner_lock | track | skip |
| turn_budget_endstate | track | pass |

