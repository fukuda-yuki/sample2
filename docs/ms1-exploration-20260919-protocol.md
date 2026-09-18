# MS1-001 exploratory acquisition protocol, 2026-09-19

This protocol implements the user's approved plan: analyze the preserved six
Runs, then acquire 18 initial Runs (six per current intervention), followed by at
most six technical-failure supplements. The implementation and evaluator are
unchanged. This is exploration, not confirmation, a winner selection procedure,
or a test of quality non-inferiority. The experimental unit is a Run.

## Population and fixed conditions

The pilot consists only of the six direct child Run directories in
`runs/acceptance-64ad09cd85ca`. Diagnostic cohorts and restored copies are excluded
from this named population, not erased. The pilot is reported separately from
new primary Runs and supplements. All attempts remain visible, including failed,
unscored, interrupted, undispatched and incompletely measured slots.

The task is MS1-001, 29 public requirements, evaluation 1.2.0, source revision
`2967afb9d69488641df0d154e2ad5827a7820e71`. The current three profiles are explore,
preload (20 fixed source blocks), and explained (one fixed existing explanation).
The source, public request, profiles, prepared worker/evaluator/gateway image IDs,
evaluator bytes, controller bytes, and analysis rules are frozen by SHA-256 in
the adjacent machine-readable plan. The model is `deepseek-v4.1-flash`, OpenCode
is 1.17.11, implementation time is 1800 seconds per Run, provider timeout 600
seconds, concurrency one, automatic compaction enabled, pruning disabled, no
subagents. There is no added token cutoff, fallback model, live smoke Run,
LLM-written preparation, or treatment change in this batch.

Each Run starts with fresh native session, workspace and state directories;
previous implementations are never supplied. Cached dependencies are identical
prepared assets. Provider cache cannot be reset or fixed; its reported counts,
timestamps and order are recorded. Token accounting includes cached input.

## Questions and preregistered exploratory hypotheses

H1 — **Initial source delivery versus later acquisition**. Preload may reduce
source acquisition while its initial context remains in later requests. Check
initial input, retained block counts, subsequent visible source ranges, calls,
mean input and total input/output together. Contradictions include no acquisition
reduction, later context removal, and lower totals fully associated with fewer
calls. This is a hypothesis about the policy as a whole, not isolated compression.

H2 — **Large tool outputs carried forward**. Large seed-source reads and runtime
logs may be retained over many later calls, corresponding to substantial input
growth across more than one intervention. Check the largest input increments and
the five outputs with the greatest measured character exposure per Run. Exposure
is the sum of visible output characters over actual later requests; it is not a
token attribution or a counterfactual saving. Contradictions include absent later
delivery, small/reduced context, or source processing that does not expose the
large text. No instruction to suppress output is added to this batch.

H3 — **Number and grouping of actions**. Differences in tool calls per model
request and repeated validation/revision can increase the request count even
when average input is lower. Compare total actions, multi-tool request counts,
first build position, build errors, test failure text and revisions. Tool actions
are descriptive and are not counted as independent experiments. A write/edit is
not proof of a failed implementation or of unnecessary work.

These hypotheses are candidates selected after the pilot. New categories or
hypotheses discovered after acquisition begins must be labelled post hoc.

## Analysis definitions

Provider SSE input/output usage is authoritative. OpenCode's native input excludes
cache reads and native output excludes reasoning in these records; neither field
can replace gateway totals. Input/output include those breakdowns once; absent
cache-write values stay null. `T_run = sum(input + output)` includes auxiliary
gateway calls. Incomplete inventory or usage makes the authoritative total null;
observed partial sums are separately labelled and never treated as full totals.

The offline analysis joins run_instance_id, request_id and tool_call_id. It checks
start/terminal inventories, hashes of transmitted requests and original SSE,
raw usage versus normalized usage, model identity and native tool mappings. It
hashes source materials before and after analysis. Analysis output is written
outside source Run directories and is not overwritten.

Action classification v1.0.0 is deterministic and multi-label: environment,
discovery, source_read, implementation, build, validation, revision, plus
validation_setup, inspection, planning, cleanup and other_unknown. The latter
categories avoid forcing unsupported interpretations. Shell syntax is inspected
but never executed. A command combining activities receives all matching labels;
its tokens are never arbitrarily divided among those activities. Reported label
counts overlap and must not be summed as a partition.

Read tools yield exact observed line numbers. Shell source exposure requires at
least three contiguous original lines and 30 non-space characters actually in the
output. Candidate paths alone do not establish delivery. Unresolved variables,
wildcards, count-only processing and unknown ranges remain indeterminate. Initial
preload lines enter the exposure history. Reacquisition distinguishes first range,
unchanged range, partial overlap, after observed edit, changed content with unknown
edit, and indeterminate. Shell mutations conservatively invalidate unchangedness
claims for previously read editable workspace files. None of these labels means
"waste". Cross-file duplication is investigated as a case, not inferred from names.

Input character dimensions cover message roles, assistant tool arguments, tool
schemas, newly seen and previously seen message variants. A disappeared message
hash means a variant was removed or changed, not proof of semantic compaction.
Retention of original prompts and injected blocks is checked directly in actual
user messages using the existing numbered-Read matching rules.

## Schedule, errors and stopping

All six permutations of three interventions occur once. The six block order is
shuffled once with a recorded random seed before dispatch. Slots 1–18 and their
Run IDs are immutable. Use the ordinary harness `run` CLI with an explicit new
batch directory. Journal each dispatch before starting it; never replay an
uncertain dispatch or reuse a Run ID.

Quality failure and ordinary 1800-second implementation timeout are retained and
not supplemented. Try offline usage reconciliation or rescoring for recoverable
technical problems before spending another model Run. An unexpected recovery need
pauses the driver for inspection; that is not a reason to discard the attempt.
Unrecoverable provider/transport/measurement failures may be supplemented only
after all 18 initial slots, in original slot order: one supplement per eligible
slot, at most six overall. Supplements have separate Run IDs, a replacement_for
link, and no original block assignment. They do not replace primary observations.

Authentication/quota HTTP 401/402/403/429, model/policy or frozen-condition mismatch,
unconfirmed stop, isolation failure, identity/integrity or preservation failure
halts acquisition. No treatment or timeout edits are permitted within this batch.
Unstarted slots remain explicitly unstarted. Stop after the fixed schedule and
allowed supplements, or a documented blocking condition, never after significance
or a desired result appears. The maximum implementation allowance is 9 hours for
18 initial Runs and 3 additional hours for six supplements; evaluation and
preservation time are outside this controller budget.

## Reporting and next decision

Report all individual outcomes and requirement judgments with token counts;
show mean, median, sample standard deviation, IQR and range per intervention and
cohort. Show complete primary-block pair differences. Success-only summaries are
secondary. Do not pool historical six Runs with new eighteen Runs or supplements.
No significance testing or confirmatory claim is planned for this small batch.

For each hypothesis, retain supporting cases, counterexamples and unknowns. Give
priority to repeated mechanisms, substantial observed input/call differences, and
a minimal controllable intervention. Select one next main hypothesis only when
the evidence warrants it; otherwise state the missing evidence. Fix intervention,
unchanged information, predictions and falsification criteria before future fresh
confirmation data. Confirmation sample size requires separately chosen meaningful
effect/precision, quality criterion and resources.

Human review follows exploration, before confirmation. In each arm choose the
complete, quality-passing Run closest to that arm's median total tokens (ties:
earlier execution). With no such Run, inspect its failures. Prepare ordinary
purchase, invalid-checkout state retention, cross-session isolation, and restart
order-retention steps, mapped to the 29 requirements. Automation is not human
acceptance. The current contract does not establish full visual fidelity or
preservation of every order-detail field. A required contract change gets a new
version and separate batch. Include a proposed update of the misc research
protocol; do not claim that it has been published or accepted.

## References

- [Transcript and outcome evaluation](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [Randomized blocks](https://www.itl.nist.gov/div898/handbook/pri/section3/pri332.htm)
- [Sample size justification](https://lakens.github.io/statistical_inferences/08-samplesizejustification.html)
- [Research canonical protocol](https://github.com/fukuda-yuki/misc/blob/main/knowledge/projects/lsken-2026-04/research/protocol.md)
