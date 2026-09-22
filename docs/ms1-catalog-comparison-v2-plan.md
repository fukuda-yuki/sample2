# MS1 catalog comparison v2: estimate effects within verified resources

The later [execution preparation](ms1-catalog-execution-ready.md) adopts and fixes
320 pairs under the clarified resource policy, while retaining this document and
its unallocated machine plan as design history. Scientific comparisons below
remain applicable. Dispatch requires separate approval of the new frozen plan.

**Recommendation: one fixed, resource-bounded paired comparison whose primary
outputs are total-token and all-29-pass-rate differences, their uncertainty,
and descriptive behavior. No Run count is adopted yet.** Quality superiority
is an additional conclusion, not the definition of a useful study. No margin
has been justified to establish quality maintenance. No new model Run,
re-pilot, historical 24-product re-evaluation or ZIP recreation is authorized.

The [machine plan](../research/protocols/ms1-catalog-comparison-v2.json) has
`pairs`, `runs_per_condition` and `maximum_runs` set to null, and an empty
allocation. This is deliberate: current remaining usage is readable, but it
does not establish model-specific Run capacity or available execution hours.
Replacing 320 with another unsupported number would not resolve that gap.

The technical pilot and evaluator acceptance remain in force. The model stays
**deepseek-v4.1-flash through the existing OpenCode Go subscription**. The user
confirmed the subscription and use of the Windows user environment variable
`OPENCODE_GO_API_KEY` on 2026-09-21. No credential value is part of this report.

## Status and preserved history

[PR #14](https://github.com/fukuda-yuki/sample2/pull/14) merged at
2026-09-20 22:50:21 JST, head
`dfcf35de006f34590c8182fac09cef100b87e07a`, merge
`ac361e2b393c678365761725d99411f138244436`. This revision starts at that merge.
The old “unpublished” statement describes the earlier report time only.

The [v1 plan](ms1-catalog-confirmatory-plan.md), its machine JSON, simulations,
freeze receipt, pilot smoke output, validation and misc proposal remain
byte-for-byte historical files. Their 320-pair recommendation is **not adopted**.
Use the Git revision above for the corresponding original analyzer; the current
analyzer explicitly rejects v1 as an execution plan. Historical freeze hashes
refer to historical code, not to a claim that current code has not changed.

This revision's [resource comparison](ms1-catalog-comparison-v2-resources.md),
[validation](ms1-catalog-comparison-v2-validation.md) and
[misc proposal](ms1-catalog-comparison-v2-misc-proposal.md) form one review unit.
The misc proposal remains unapplied.

## Question, units and fixed conditions

With identical original source, derived catalog and retrieval capabilities,
how does omitting the initial source excerpt affect requirement fulfillment,
behavior and provider input-plus-output tokens over **all assigned Runs**?
The sole intervention remains the appended initial source packet. Later source
retrieval is allowed in both conditions. Calls are nested observations, not
independent samples. The task, source, model, agent, evaluator, browser pins,
tools, timeout and concurrency stay as in the accepted input contract and
pilot. No deletion hints or new conditions are introduced.

Each adjacent pair has one Run per condition with independently randomized
order. Retain the saved seed and allocation algorithm; do not search seeds,
re-pair observations or regroup by outcomes. Once a resource-supported size
is selected **before outcomes**, save its complete allocation and plan hash
before any dispatch. Start pairs only with capacity for both members. Record
UTC times, order, pauses, cache/usage shapes and identities. No outcome-driven
early success stop, extension, replacement or success-only substitution.

The four pilot Runs and all historical/exploratory Runs remain excluded from
the future comparison population. Resource extrapolations from the pilot are
explicit references, not fitted population distributions or additional samples.

## Metric-specific decisions

| Output | Estimand / interval | Conditions for inference | Interpretation |
|---|---|---|---|
| Primary tokens | Arithmetic mean of paired `T_compact - T_expanded`; Student t two-sided 95% interval | Valid shared/token provenance; complete provider input + output over every call in every assigned Run; nondegenerate interval | Upper bound < 0 supports a reduction. Report the difference and interval even if reduction is unsupported. |
| Primary quality | Difference in probabilities of passing all 29 requirements, compact minus expanded | Valid shared/quality provenance; every assigned binary outcome determined | Conservative paired interval from two 97.5% Clopper-Pearson discordance intervals. Lower bound > 0 supports **relative superiority**; upper bound < 0 supports degradation; otherwise the direction remains unresolved. |
| Quality maintenance | No justified loss margin | No maintenance/noninferiority test is adopted | Neither equality of point estimates nor an interval spanning zero establishes maintenance. Show the interval and its limits. |
| Additional conjunction | Both directional supports | Both metrics independently satisfy their inference conditions | Can support token reduction with relative quality superiority. It does not establish absolute practical adequacy, human acceptance or research-wide success. |
| Behavior | Calls, input length, retrieval, retention and implementation/verification activity, by Run and condition | Saved observations and explicit coverage/audit state | Descriptive mechanisms to investigate; not causal proof or additional confirmatory tests. |

The original 600,000-token target is retained as a **planning scenario** and
additional minimum-effect flag, gated by token eligibility. Detecting a true
20% reduction against zero differs from establishing at least 600,000 fewer
tokens. Neither is the sole criterion for obtaining useful comparative evidence.

Retain the fixed pair bootstrap (20,000 resamples, seed 2026092101), ratio of
arithmetic means and order diagnostics as secondary sensitivities. No median,
log-scale, trimmed or success-only replacement of the primary mean. An identical
observed token difference retains its point estimate but has no population
zero-width interval or support flag; quality inference is still assessed.

Intervals are **marginal 95% intervals**, not a simultaneous 95% confidence
region for both effects. The optional conjunction is an intersection of
directional claims. Do not multiply endpoint powers or treat success on either
endpoint as a study-wide 5% test. Per-requirement and behavior comparisons are
descriptive. Independent, identically distributed pairs are the inferential
assumption; skew, shared provider regimes and dependence across days can limit
the t approximation and population interpretation. The v1 scenarios do not
guarantee coverage under arbitrary heavy tails or provider drift.

This distinguishes noninferiority-bound justification from requiring
superiority, consistent with [Lakens, equivalence and interval hypotheses](https://lakens.github.io/statistical_inferences/09-equivalencetest.html).

## Determined outcomes, incomplete inspection and invalid identity

| Observation state | Tokens | All-29 binary outcome | Separate record |
|---|---|---|---|
| At least one verified requirement failure; other requirements unobserved | Infer if usage/provenance is complete | **0**, with valid artifact/evaluator identity; this is a determined failure | Missing/blocked requirement IDs and full-inspection status |
| No verified failure and some requirements unobserved | Infer if usage/provenance is complete | Unknown | All-assigned pass-rate bounds and worst/best paired interval envelope |
| Complete adopted evaluation, all requirements pass | Infer if usage/provenance is complete | 1 | Per-requirement results |
| True usage missing after recovery | No all-assigned token mean or primary interval | Infer if every binary outcome is valid and known | Known token subtotals and complete pairs as secondary only |
| Wrong model/task/input or unrecognized provenance fault | Block affected shared inference | Block affected shared inference | Keep original recorded facts; no supportive flags |
| Wrong evaluator/artifact/specification identity | Token inference can remain available | A recorded fail/pass cannot be treated as trusted; unknown for inference | Recorded outcome and quality integrity fault |
| Incomplete cleanup or behavior audit with otherwise valid measured endpoints | No automatic veto | No automatic veto | Operational failure/coverage remains visible; further dispatch remains stopped as required |

Only recognized usage or behavior audit categories are separated. Unknown
provenance faults stay shared. Invalid totals still fail input validation;
unknown totals are never silently zero. A missing allocated row stays in its
fixed denominator. A confirmed no-dispatch zero requires affirmative saved
evidence; absence of calls alone does not establish zero usage.

For truly unknown quality outcomes, report all-assigned worst/best sample
bounds and conservative interval envelopes; do not promote the observed
complete subset to the primary population. v2 conservatively withholds
superiority support when binary outcomes are unknown, even if the envelope
is directional. Invalid-identity recorded outcomes remain visible separately.

Technical stops, uncertain dispatch and cleanup rules still constrain
**acquisition**. Do not replay in-flight/uncertain slots. Any future allowed
evaluation recovery uses the same frozen artifact, preserves attempts and
respects the existing recovery limit. This revision performs none. Separating
metric inference does not turn operational non-success into completion.

## Resource allocation recommendation

Use the [five existing candidates and actual resource evidence](ms1-catalog-comparison-v2-resources.md)
to choose a single fixed cohort only after all of the following are documented:

1. Model-specific capacity across the intended account windows and any changes
   to limits/rates over the intended calendar period; no purchased overage or
   alternative-model fallback is assumed.
2. Hours that can actually be allocated, including runtime, preparation,
   evaluation, preservation and recovery. Hardware uptime is not permission
   to use every hour or the entire subscription.
3. Dedicated storage and reserve for growth, preserved originals, evaluations
   and archives. Current free space is not all reserved for this task.
4. What the selected candidate's uncertainty could usefully establish, and
   what it could not. Larger N is not automatically worth the cost. If none
   is both feasible and informative, acquire none; do not force the smallest
   candidate merely because it appears cheapest.

The current recommendation is therefore **adopt the v2 inference/resource
design; defer numerical allocation**. The known account percentages and disk
snapshot do not close the remaining capacity/hours gaps. Resource-constrained
sample-size justification must retain sensitivity and precision limits, as
described by [Lakens, sample-size justification](https://lakens.github.io/statistical_inferences/08-samplesizejustification.html).

## Analysis boundary and ordinary offline interface

`catalog_confirmatory.analyze` is the shared validation boundary. Confirmatory
use requires a saved allocated v2 plan via `plan_path`; its parsed value must
match the passed plan object. Both the observation `plan_sha256` and receipt
`analysis_plan_sha256` must match the **exact file bytes**, preserving the
existing observation reader's hash convention.

A receipt may be embedded in observations, supplied as `--launch-receipt`, or
passed as a function argument. Each uses the same validator. Conflicting
embedded/explicit receipts are rejected. The mandatory fields include a true
boolean pre-dispatch confirmation, UTC timestamp, verified resource/pin
records with references, journal path and complete required code hashes.
The required code set includes the analyzer, observation reader, behavior
classifier and analysis dependency lock. Empty/subset hashes and changed code
are rejected. Paths must remain inside the repository.

Content hashes do not prove that an attestation is truthful or was actually
made before dispatch. Inspect the referenced resource/pin evidence and
append-only dispatch journal; a synthetically constructed test receipt is
never a real launch authorization. The current machine plan intentionally
cannot pass confirmatory allocation validation.

After a future authorized freeze, the ordinary offline call is:

```powershell
artifacts/catalog-confirmatory-design/analysis-env/Scripts/python.exe -m research.catalog_confirmatory --plan <saved-plan.json> --observations <saved-observations.json> --launch-receipt <receipt.json> --out <new-result.json>
```

Direct callers use `analyze(plan, observations, plan_path=saved_plan_path,
launch_receipt=receipt)`. The receipt argument may be omitted when embedded.
Outputs never overwrite existing evidence. `pilot_smoke` is descriptive only
and cannot set token, target-reduction, quality or joint support flags.

`decision` now reports inference availability (`both_metrics_estimable`,
`tokens_estimable_quality_unresolved`, `quality_estimable_tokens_unresolved`,
or `indeterminate`), not efficacy. `token_inference`, `quality` and
`conclusions` carry the separate scientific statements; `operational` retains
inspection, cleanup and behavior status. Consumers of the old single decision
string must use output schema version 2.
