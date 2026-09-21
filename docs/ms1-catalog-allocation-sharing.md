# Full resource allocation supports a 320-pair working proposal with shareable evidence

The user allocated this PC continuously, 100% of the existing OpenCode Go
allowance, and no discretionary minimum free-disk reserve on 2026-09-21.
The study calendar is delegated. Additional subscriptions can be considered
if needed. The user wants detailed SQLite OTLP and all analysis inputs shared
through `fukuda-yuki/sample2`, so other people can investigate the results.
The [machine-readable resource record](../research/protocols/ms1-catalog-resource-allocation-20260921.json)
keeps these choices separate from launch authorization.

**Use 320 adjacent pairs / 640 Runs as the working candidate.** This is a
planning recommendation, not an adopted execution allocation or authorization.
The accepted [v2 protocol](../research/protocols/ms1-catalog-comparison-v2.json)
remains unchanged, unallocated and `launch.authorized=false`. No model,
evaluator, telemetry importer, archive builder or historical re-evaluation was
run in this follow-up. No subscription was purchased or account setting changed.

## Why this candidate, and what it cannot resolve

The [saved comparison](ms1-catalog-comparison-v2-resources.md) remains the
statistical source. Of the five existing candidates, 320 is the smallest whose
reference token-reduction support exceeds 80% and whose mean quality interval
half-width is below 10 percentage points. These are the **planning resolution
judgments used for this recommendation**, not user-specified quality tolerances,
new empirical findings, guaranteed precision or mandatory research-success gates.

At 320 pairs the saved scenarios give 90.66% support for a true 20% token
reduction and a 9.44 pp mean quality interval half-width. This can inform whether
to pursue a better-targeted follow-up, or whether the token saving comes with
large quality uncertainty or visible degradation. It cannot establish quality
maintenance or reliably resolve a 5 pp quality change. All-29 success rates,
individual requirements, behavior, failures and missingness remain available
for independent interpretation.

At 160 pairs, reference token sensitivity is 64.77% and quality half-width
13.46 pp. At 640 pairs, they become 99.46% and 6.63 pp, while resource usage
doubles. The extra 640-pair precision still does not establish maintenance and
increases the all-assigned missingness burden. Unlimited allowed uptime is not
a reason to select the largest cohort. The existing residual-missingness
sensitivity remains applicable; the recommendation does not relax it.

## Capacity and calendar

The new [read-only review](../research/design-results/catalog-allocation-review-20260921.json)
binds four saved normalized usage files and SQLite databases by SHA-256. Input
tokens total 12,555,186, including 11,903,872 cached reads (94.8124%); output
tokens total 168,718. These are four technical Runs, not a population model.

Using the [official rates](https://opencode.ai/docs/ja/go/#利用制限) checked on
2026-09-21, the formula is
`((input - cache_read) * input_rate + cache_read * cache_rate + output * output_rate) / 1e6`.
It avoids charging cached input twice. The four-Run cost reference is $0.23464
off-peak and $0.46928 peak. These are quota-denominated references, not invoices.
Unreported cache-write usage remains null.

| Candidate pairs | Saved cache-mix quota reference, off-peak to peak | Runtime reference / sum of Run timeouts | Full retained storage reference |
|---:|---:|---:|---:|
| 40 | $4.69-$9.39 | 16.56 h / 40 h | 34.56 GiB |
| 80 | $9.39-$18.77 | 33.12 h / 80 h | 69.12 GiB |
| 160 | $18.77-$37.54 | 66.25 h / 160 h | 138.24 GiB |
| 320 | $37.54-$75.08 | 132.49 h / 320 h | 276.48 GiB |
| 640 | $75.08-$150.17 | 264.99 h / 640 h | 552.95 GiB |

At 320 pairs, adopted scoring spans add a 5.21 h reference. Preparation,
preservation, uploads, rate-limit waits, recovery and human work are additional.
The existing no-cache/all-cache stress scenarios remain in the older comparison;
the observed-cache reference must not replace them as a bound.

Scheduling recommendation: after a separate start approval, run serial adjacent
pairs primarily off-peak. On current terms that provides 133 off-peak hours per
calendar week, before quota waits. Allow a **six-week initial operating window**
from approval, with a readiness check before the first pair and an operational
review after two weeks. This is a scheduling judgment allowing for quota reset
and archival work, not a derived completion guarantee or outcome-based stop.
If acquisition is incomplete, keep the fixed N and all allocated slots; a
calendar extension cannot add replacements or new pairs. Provider/identity
drift remains a stop condition. Do not choose seeds, pauses or extensions from
observed token/quality effects.

The 94.8% pilot cache fraction is not guaranteed. The public $60 promotional
monthly allowance ends September 27 (normally $15); rolling/weekly limits are
20%/50%. The saved account readback predates this follow-up. Do not assume that
an unused promotional amount carries forward, that the entire monthly amount
is available in one week, or that different subscriptions can safely substitute
for each other. Confirm actual window limits and remaining usage before start
and before every pair. A pair must have capacity for both members. Pausing for
quota reset is preferable to changing the fixed provider/model configuration.
An additional subscription is an available user option, not current capacity;
no automatic purchase, paid balance fallback or account rotation is configured.

The current C: free-space readback is about 286.37 GiB. The 320-pair retention
reference leaves about 9.89 GiB before additional growth. The user reserve is
zero, but writes still require physical capacity. Check the next pair's work,
SQLite finalization and upload staging against current free space; pause before
dispatch if they do not fit. Do not count GitHub as local disk already freed.
No original is deleted by this proposal. Verified remote storage and a bounded
local staging strategy are acquisition prerequisites, not already proven facts.

## Evidence to retain and share

The existing gateway records each request in `telemetry/monitor.db`, including
raw OTLP, trace/span/request identity, model, request status, timestamps and
reported input/output/cache/reasoning tokens. The four databases pass read-only
SQLite integrity checks and exact OTLP readback for **218 request spans**. Their
total size is about 2.86 MiB; proportional storage for 640 Runs is 458.13 MiB.
These are gateway observations. There are no native OpenCode OTLP span events
in these four files, and no claim to unobserved internal model reasoning.

The [read-only SQL](../research/sql/catalog_otel_requests.sql) exposes request
rows and retains the underlying JSON. It does not silently turn null usage into
zero or certify a complete Run from the presence of some spans. SQLite alone
does not contain the complete experiment. The release manifest must cover:

| Evidence | Why another analyst needs it |
|---|---|
| Fixed allocation, seed, exact plan/code hashes, dispatch journal and all allocated slot states | Establish denominator, pairing, chronology, unstarted/uncertain work and identity |
| Each sealed `telemetry/monitor.db`, original gateway OTLP and link/readback receipt | Query detailed observed request spans; reproduce telemetry projection |
| Original provider request JSON, response SSE, starts/ends, normalized usage and provenance | Inspect context, content, tool returns, usage parsing, missingness and original evidence |
| Native agent events/state, tool calls/results, prompts, source packet and input identities | Study retrieval, context growth, retention, implementation and validation behavior |
| Frozen generated source, collection snapshot and original workspace evidence | Inspect product successes and failures without regeneration |
| Every evaluation attempt, adoption index, all 29 requirement outcomes, HTTP/browser evidence, screenshots, event logs and evaluation DB | Distinguish quality, coverage, evaluator faults, cleanup, retries and `human_review: not_run` |
| Exact harness/reader/evaluator source and binaries, dependency locks, image digests, runtime/browser pins and required environment artifacts | Reproduce extraction/analysis elsewhere; disclose any unavailable dependency |
| Derived Run/pair/call/action/requirement tables, analysis scripts, SQL, dictionary, licenses, README and claim-to-evidence references | Support both prespecified inference and independently labeled exploratory analyses |

Preserve failed and incomplete Runs with explicit missing files/reasons. A
failure does not disappear from the dataset because no complete archive exists.
Keep pilot, historical and future comparison cohorts distinct. New exploratory
analyses must identify their population, exclusions and assumptions and cannot
replace the frozen primary comparison. Different reviewers should receive the
same hashed data and retain disagreements, not only a consensus narrative.
No reviewers were contacted or analyses delegated in this follow-up.

## Distribution through the same GitHub repository

The repository is currently public, and the user has requested sharing the
research data there. GitHub [blocks ordinary Git files over 100 MiB and recommends
small repositories](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github).
Use Git for protocols, source, SQL, data dictionaries, small summaries and
hash/URL manifests. Use **Release assets in this same repository** for immutable
SQLite files and the complete accompanying evidence. This keeps the requested
GitHub destination without repeatedly adding large database revisions to Git.

[Release limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
are 1,000 assets per release and under 2 GiB per file. Use at most 32 Runs per
release and split large payloads into parts of at most 1 GiB. Preserve original
file bytes, sizes, paths, cohort/Run/instance IDs, hashes and reassembly order.
The per-release asset count is checked after splitting; create another release
if the asset count would exceed the limit. SQLite files are sealed snapshots,
not active files with omitted WAL state.

The delivery sequence for future data is:

1. Complete or checkpoint the Run, preserve all attempts, finalize a consistent
   SQLite snapshot and record an explicit file inventory with hashes.
2. Prepare a public copy; inspect all files, including SQLite text/BLOB content,
   native state, command logs and archives for credentials and private context.
   Never publish API keys, authentication state or operational capability tokens.
   Keep originals unchanged. Record any redacted/excluded path, reason and
   analytical consequence; do not claim an exact public reproduction when a
   required input is unavailable.
3. Upload immutable assets to the intended release. Record repository, release
   and asset IDs. Independently download each asset and verify size/hash, then
   reconstruct the corpus in a fresh directory and perform offline extraction
   and analysis checks. This does not rerun the model or rejudge old products.
4. Push the Git manifest and reader instructions only after asset readback and
   restoration pass. Verify the remote commit and links. Report local, uploaded,
   downloaded/verified and published states separately.

This pipeline is specified here; **the public-data sanitizer, release uploader,
download/restore gate and comprehensive cross-Run SQLite analysis index have not
been implemented or accepted**. Existing preservation code and per-Run databases
are reusable. The live acquisition controller is not changed in this follow-up.
No raw research data has been uploaded by this work, and no old ZIP was rebuilt.

## Reviewable closeout and remaining gates

Resource allocation preferences are now resolved. The numerical working
recommendation and data contract are concrete. The accepted execution plan
remains unallocated until operational capacity and the sharing path are verified;
then save its 640-slot allocation, exact plan hash, code/environment pins and
pre-dispatch evidence before asking for the separate experiment start approval.
Do not manufacture a verified launch receipt from this proposal.

Validation: the new offline helper/SQL's ten focused tests pass, covering cache
accounting, unknown/invalid usage, immutable DB readback, changed payloads,
duplicate requests, uncheckpointed SQLite, SQL projection and no-overwrite behavior. The first
seven-test attempt had four passes and three temporary-fixture cleanup errors
because SQLite connections were not explicitly closed on Windows; the fixture
was corrected; the nine-test rerun and the final ten-test run passed. No historical test result
is relabeled as a new run. The four original DBs and input files were hashed
before and after the real readback and remained unchanged.
The [validation record](../research/design-results/catalog-allocation-validation-20260921.json)
retains the separate attempts, log hashes, 218-row SQL readback and unchanged
PR #15 source hashes.

Reproduce into a **new** output path:

```powershell
artifacts/catalog-confirmatory-design/analysis-env/Scripts/python.exe -B -m research.catalog_allocation_review --out <new-review.json>
artifacts/catalog-confirmatory-design/analysis-env/Scripts/python.exe -B -m unittest research.tests.test_catalog_allocation_review -v
```

The disk/time fields describe the reproduction time; the frozen source-derived
totals should match. This check is not a fresh provider usage readback, original
provider-call re-audit, evaluator run, quality result or launch authorization.
