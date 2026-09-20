# Proposed experiment-specific amendment to misc (not applied)

Reviewed canonical revision: **797dde53f29dd3512d91699dc69b5cd8a8d607c9**,
read from GitHub on 2026-09-20. The sources are the
[Research Protocol](https://github.com/fukuda-yuki/misc/blob/797dde53f29dd3512d91699dc69b5cd8a8d607c9/knowledge/projects/lsken-2026-04/research/protocol.md),
[Research Questions](https://github.com/fukuda-yuki/misc/blob/797dde53f29dd3512d91699dc69b5cd8a8d607c9/knowledge/projects/lsken-2026-04/research/research-questions.md),
and [Research Plan](https://github.com/fukuda-yuki/misc/blob/797dde53f29dd3512d91699dc69b5cd8a8d607c9/knowledge/projects/lsken-2026-04/planning/research-plan.md).
The Protocol still specifies VS Code GitHub Copilot, simulated maintenance,
an initial N=10 pilot, and rank/permutation methods with median contrasts.
None of these three sources specifies a numeric acceptable drop in the
all-requirement pass probability for this modernization task.

This is a proposed scoped addition, not a claim that those sources were
already revised or that the entire research program is this experiment.

## Exact placement and proposed additions

| Canonical location | Existing scope | Proposed scoped change |
|---|---|---|
| Protocol: rationale and population | Copilot and simulated maintenance | Add a named modernization extension, MS1-CATALOG-CONFIRMATORY-V1; preserve the existing track and distinguish its evidence |
| Protocol: observation | Copilot OTel and Langfuse | Add gateway provider request/response and OpenCode native trace as this extension's primary acquisition records; monitor ingestion is derived, not native OpenCode OTel evidence |
| Protocol: phases | Baseline, simulated maintenance, anti-pattern validation | Register exploration and accepted connection pilot as prior phases, followed by the fixed, **not yet executed** confirmation plan |
| Protocol: quality | Qualitative criteria per maintenance type | Retain them; add public 29-requirement Run success and the zero-loss relative interval rule for this task only; no invented population floor or positive loss margin |
| Protocol: analysis | Rank/permutation tests and median CI | Add the paired arithmetic total-token mean and paired binary interval as the prespecified methods for this extension; do not silently substitute ranks for its mean estimand |
| Research Questions / Plan: scope | Japanese enterprise-like maintenance and Copilot | Add a subsidiary question about initial source return range during legacy modernization; preserve the existing main questions and untested generalization boundaries |
| Dataset / Experiment / Analysis concepts | Actual work only | Register the offline design/analysis calculation now if adopted; create acquisition/result records only when they actually occur |

Suggested insertion under **Rationale and population**:

> Alongside the Copilot simulated-maintenance track, the research includes a
> bounded replication/extension track on legacy-system modernization. Its
> first controlled task is the partial MVC Music Store modernization MS1-001.
> OpenCode 1.17.11 and deepseek-v4.1-flash are the execution conditions of this
> experiment, not replacements for the research program's general scope.
> Generalization to other tasks, models, agents, languages or organizations
> requires separate evidence.

Suggested subsidiary question:

> When both conditions can use identical original source, derived data and
> retrieval tools, how does omitting a large source excerpt from the initial
> input affect requirement compliance and provider-reported total tokens over
> every assigned Run, including failures and timeouts? Later acquisition and
> retention are measured responses rather than prohibited behavior.

Suggested insertion under **Protocol and phases**:

> The initial exploration and the accepted four-Run technical connection pilot
> are preliminary evidence and do not enter confirmatory estimation. The
> experiment-specific plan in sample2 fixes 320 fresh pairs, independent saved
> within-pair order, arithmetic Run-token mean difference, all-29 success,
> conservative paired quality intervals, no replacements, and technical
> recovery on the same artifacts. It is a frozen design awaiting separate
> acquisition authorization, not an executed experiment or efficacy result.

Suggested insertion under **Quality and interpretation**:

> No positive allowable quality-loss margin or absolute population pass-rate
> floor has been justified for this extension. A strict relative quality
> condition requires the lower paired 95% difference bound to exceed zero.
> Equal point estimates, nonsignificance, or all observed successes do not
> establish maintenance under this rule. Token reduction alone, especially
> early failed products, is insufficient for a joint claim. Even joint
> relative support does not establish practical adequacy or human acceptance.

The former sample2 [exploration proposal](ms1-exploration-research-protocol-proposal.md)
remains historical. Its not-yet-implemented intervention and extra human-review
launch gate are not carried forward as current requirements: the user has
accepted technical connection and has not requested another pilot or evaluator
change. Human review remains `not_run`, distinct from automated public-contract
evaluation. No work on a self-improvement demo or observability redesign is
part of this amendment.

## Authority and traceability

`misc` remains the research canonical source. `sample2` owns this task's input
contract, evaluator and executable experiment/analysis implementation. Link
the [fixed plan](ms1-catalog-confirmatory-plan.md), machine plan, design
calculations, accepted pilot, implementation revision and freeze checksums
from the canonical extension. Do not copy evolving specifications into memory
or replace the broader research plan with this single task. The authority for
pilot acceptance and this work's scope is the user's current instruction;
the GitHub sources establish the existing text and its still-unapplied gap.
