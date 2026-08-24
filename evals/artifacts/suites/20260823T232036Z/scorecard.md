# Eval scorecard — 20260823T232036Z

1 simulated scenarios, 0 regressions caught before merge, zero hallucinated verdicts (judge-oracle agreement 100.0%, pass^5 on 1/1).

git `33d65d9` · engine `judge-swap-demo`

| scenario | channel | verdict | pass^k | turns | ttfa p50 | judge Δ | stability |
|---|---|---|---|---|---|---|---|
| co-0001-top-pick-accepts | voice | CONFIRMED_CORRECT | 1/1 ✓ | 2.0 | 1835.4ms | 100.0% | stable |

## All metrics

### co-0001-top-pick-accepts  ·  voice  ·  `judge-swap-demo`

| metric | role | value |
|---|---|---|
| oracle_verdict | gate | CONFIRMED_CORRECT |
| pass_k | gate | True |
| k | track | 1 |
| passes | track | 1 |
| ttfa_p50_ms | track | 1835.4ms |
| full_turn_p95_ms | track | 1835.4ms |
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

