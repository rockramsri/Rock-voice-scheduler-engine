# Eval scorecard — 20260823T232643Z

5 simulated scenarios, 0 regressions caught before merge, zero hallucinated verdicts (judge-oracle agreement 100.0%, pass^5 on 5/5).

git `33d65d9` · engine `cascade`

| scenario | channel | verdict | pass^k | turns | ttfa p50 | judge Δ | stability |
|---|---|---|---|---|---|---|---|
| co-0001-top-pick-accepts | voice | CONFIRMED_CORRECT | 5/5 ✓ | 2.0 | 902.0ms | 100.0% | stable |
| co-0002-no-weekends-decline | voice | CONFIRMED_CORRECT | 5/5 ✓ | 2.0 | 896.5ms | 100.0% | stable |
| co-0003-hard-no-escalates | voice | CONFIRMED_CORRECT | 5/5 ✓ | 2.0 | 854.4ms | 100.0% | stable |
| co-0006-sms-one-shot-accept | sms | CONFIRMED_CORRECT | 5/5 ✓ | 1.0 | 247.5ms | 100.0% | stable |
| co-0014-chatty-no-intent | voice | CONFIRMED_CORRECT | 5/5 ✓ | 3.4 | 947.1ms | 100.0% | stable |

## All metrics

### co-0001-top-pick-accepts  ·  voice  ·  `cascade`

| metric | role | value |
|---|---|---|
| oracle_verdict | gate | CONFIRMED_CORRECT |
| pass_k | gate | True |
| k | track | 5 |
| passes | track | 5 |
| ttfa_p50_ms | track | 902.0ms |
| full_turn_p95_ms | track | 1593.0ms |
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
| ttfa_p50_ms | track | 896.5ms |
| full_turn_p95_ms | track | 1636.4ms |
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
| ttfa_p50_ms | track | 854.4ms |
| full_turn_p95_ms | track | 1615.8ms |
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

### co-0006-sms-one-shot-accept  ·  sms  ·  `cascade`

| metric | role | value |
|---|---|---|
| oracle_verdict | gate | CONFIRMED_CORRECT |
| pass_k | gate | True |
| k | track | 5 |
| passes | track | 5 |
| ttfa_p50_ms | track | 247.5ms |
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
| oracle_verdict | gate | CONFIRMED_CORRECT |
| pass_k | gate | True |
| k | track | 5 |
| passes | track | 5 |
| ttfa_p50_ms | track | 947.1ms |
| full_turn_p95_ms | track | 1694.3ms |
| turns_used | track | 3.4 |
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

