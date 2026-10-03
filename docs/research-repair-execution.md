# Recording and bounded pair repair

Issues [#20](https://github.com/fukuda-yuki/sample2/issues/20) and
[#23](https://github.com/fukuda-yuki/sample2/issues/23), repair base
`3dba038bced6c0a525098245a3f66d162f1b15bf`. Historical catalog Runs, plans,
verdicts and archives are retained. The old 320-slot acquisition is not resumed.

## Shared measurement contract

New Runs keep schema 2 for existing readers and add `evidence_version=3`.
The assigned cohort, plan hash, pair, slot, display ID and immutable instance
are persisted in the manifest before startup. The gateway binds request ID,
instance session ID, exact transmitted request hash and response hash.
`known_no_send`, `unknown` and `observed_send` distinguish intent from locally
observed transmission. Provider acknowledgement and saved response counts are
separate. A missing controller cannot leave initial `model_called=false` when
raw responses or observed transmission show activity.

SSE parsing retains the last cumulative usage report once, including after
cancellation and transport exceptions. Cached input is already included in
input, and reasoning is already included in output. Neither is added twice.
DONE and response existence never prove usage completeness. Truncated or
cancelled responses may have observed partial amounts but no complete total.
Unknown observed components are null. A raw/journal conflict retains both
reported alternatives and prevents a complete total. Raw SSE supplies the
observed partial amount; this is a declared provenance rule, not a silent choice.
Versioned normalization/binding receipts retain request/response/manifest hashes
while compatibility filenames remain available. Provider billing internals are
not independently observable.

`runtime.request_stop` reconciles gateway evidence under the owned Run lock
when recovering an absent controller. An unavailable daemon or wrong owner
cannot prove stop. Collection and ordinary postprocessing require confirmed
stop. No uncertain dispatched identity is sent again.

## Pair API and barriers

`research.pair_execution.execute_pair(plan, cases, batch, repo=repo,
concurrency=1)` implements one pair per call. The same API supports 2; runtime
worker concurrency remains 1. `plan` contains `plan_sha256`, `cohort`, `runtime`.
Each of exactly two cases contains `run_id`, `task`, `condition`, `attempt`,
`pair`, `slot`. The caller owns frozen-plan verification, approval and resource
admission. The manager keeps the existing byte-range `dispatch.lock`, reserves
both immutable inputs and instances, fsyncs dispatch before either worker
starts, and accepts completion by identity. It never fills a free slot from a
different pair. Child implementation receipts precede manager result updates.

`machine.implement` confirms stop, fixes that Run and records raw/snapshot
hashes immediately. Its peer need not be stopped yet. Scoring, monitor import,
archive/compression do not occur there. After both implementations stop,
`machine.postprocess` handles one Run at a time. Existing scoring and append-only
monitor imports are not repeated. Interrupted scoring/postprocessing requires
explicit reconciliation; receipts can recover completed work without model send.

`recover_pair` only reconciles dispatched instances and owned containers. It
does not start workers. Missing directories remain held. `resume_pair` requires
explicit user authorization bound to the exact journal and unsent instances,
plus a caller recheck of inputs/environment/admission. It can start only an
unstarted reserved slot, retaining its original instance. A dispatched slot is
never replayed. Caller plan/cohort/runtime and durable receipt hashes are checked
on every read, including the original evidence referenced inside a pair gate.

`record_pair_gate` requires exact plan/cohort/pair/Run-instance bindings and
hashes of original publication, independent round-trip and cleanup receipts.
It rejects a boolean-only proof. The remote asset receipt must confirm URLs and
package hash; restoration must confirm matching bytes and blocked extraction
sockets; cleanup must confirm owned targets and retained original Runs. All
three package hashes agree. Until this gate is recorded, the next pair is held.
The new receipt adapter to actual publication is a separate acceptance item;
no external publication is performed by this API.

## Task input and serializer hooks

`task_input_adapter=migration-v1` selects `migration_input.prepare(repo, task)`
before generic source preparation. Its returned immutable source/business
inputs are copied into each Run. Extra private evaluator assets are copied
from `evaluation.extra_assets` (repository-relative path to destination basename)
and included in the frozen asset hashes. Private oracle data is not worker input.

`deepseek-migration-v1` uses `/inputs`, stdin prompt transport, 1800-second Run
budget, 600-second provider timeout, OpenCode 1.17.11, the existing gateway-only
credential route, and unchanged auto compaction with `prune=false`. Preparation
is in the new namespace `artifacts/runtime/music-store-continuity-v1`.
The initial exact public prompt is checked after ordinary OpenCode serialization
at the gateway, before transmission. Arm-specific preload source is part of
that prompt; the read access and runtime settings remain common.

## Predeclared finite offline cases

| Case | Required observation |
| --- | --- |
| Controller absent, initial false, 75 saved responses | observed activity, partial sum, complete total null |
| Before send / send intent / local send before ack | three distinct evidence states; ack remains separate |
| Partial SSE with usage / without usage / DONE without usage | last report once or null; no invented complete total |
| 1085-like raw/journal conflict | both alternatives and conflict status retained |
| Storage failure before dispatch | 507, no upstream request, gateway stops |
| Reverse pair completion and serial path | correct instances, max 2/1, original receipt before barrier |
| One side unconfirmed, duplicate/wrong instance, third Run, competing manager | held or rejected; no heavy work or redispatch |
| Missing dispatched directory, next-pair gate pending | held; no replacement |
| Completed child before manager result, postprocess interruption | explicit receipt reconciliation, no duplicate processing |
| Actual OpenCode and Docker mock provider | settings/input serialization and owned resource isolation; separately retained evidence |

Relevant regression commands (no real model):

```powershell
$env:PYTHONPATH = 'outer'
python -m unittest discover -s outer/tests -p 'test_machine.py' -v
python -m unittest discover -s outer/tests -p 'test_shutdown_telemetry.py' -v
python -m unittest discover -s outer/tests -p 'test_recording_repair.py' -v
python -m unittest discover -s research/tests -p 'test_pair_execution.py' -v
```

Python state tests do not establish Windows/Docker isolation. Actual-worker
mock receipts and the separate live technical comparison are required before
calling #20 accepted. Human task/evaluator review belongs to #21/#22 and is
not replaced by these recording tests.

The ordinary worker mock probe predeclares eight recording cases and, with
`--pair`, a ninth case containing two overlapping actual OpenCode workers.
All fault cases use the ordinary worker by default; only the upstream and
credential bootstrap are replaced. The 75-response case emits 74 harmless
deterministic bash actions and a 75th action that marks the crash boundary.
`--synthetic-worker` is a diagnostic fallback and never establishes ordinary
worker acceptance. Use a fresh output directory, keep failures and do not retry
the same slots until success.

The live template is `research/protocols/technical-pair-live-20261003.json`:
exactly four maximum dispatches, MS1-CONT-A, explore/preload serial block then
paired block, unchanged 1800/600-second budgets and runtime. The blocks have
separate technical subcohorts and pending public gates. The campaign watches
reported observed usage (20 million), starts (600) and accumulated Run time
(7200 seconds) as safety stop triggers; polling can observe a threshold only
after already sent traffic. Unknown totals are missing observations. No retries,
replacements or extra passing trials are authorized. Product quality failure
is retained and is not a speed-test exclusion. Actual external-publication time
remains `not_run`, so local speed/safety results cannot complete all of #20.

Prepare exact code/runtime/input/evaluator and mock hashes without dispatch:

```powershell
python outer/verify/technical-pair-live.py --mode prepare --repo <integrated-repo> --out <new-technical-cohort> --mock-receipt <mock-result.json> --browser-probe <verified-browser-probe.json>
```

The corresponding `--mode execute` is exclusively the predeclared technical
test, using the existing Windows User credential through gateway stdin. It is
not a new-study command and cannot resume the old catalog cohort.

## Recorded ordinary-worker acceptance

The final integrated ordinary OpenCode mock campaign is retained at
`runs/_rm35/result.json` in `work/repair-integration-20261003`. It passed all
ten fixed Runs at integration HEAD `35e4ab9464d79cc472abaacf01c086aab19b69df`;
the result SHA256 is
`952537b2da8cd19f0b974bf64a248286435032afbc0f6a7a71ae3d542d02eeef`.
All cases used the normal worker; only the upstream/credential bootstrap was
replaced, with zero real model calls. The original too-long output-directory
failure is retained separately and occurred before any worker/model dispatch.
The short-root correction retained the same fixed cases and expectations.

The absent-controller case preserved 75 responses, attributed model activity,
1850 observed tokens and an incomplete total (`null`). Partial usage preserved
25 observed tokens with total `null`; partial/no-usage, DONE-only and send-before-
ack did not invent totals. The storage failure remained unknown rather than a
false zero. The paired actual workers overlapped by 8.255555 seconds, retained
their own instance-bound originals, and both stopped before serial boundary
postprocessing. That boundary probe did not run the evaluator or external gate.

`runs/_rm35/serializer-comparison.json` proves the actual first upstream prompt:
explore transmitted zero source blocks, preload transmitted all seven; common
public request SHA256 was
`5362605e020d7490611cfcfcae89d299879377965beccf48c8c72587f77d3112`.
Model, tools, permissions, read scope, compaction and retention were common.
The diagnostic mock budget was 120 seconds, whereas the separately frozen live
technical budget remains 1800 seconds. Serialization proves bytes reached the
request, not model understanding or distribution equivalence.

Recorded evaluator infrastructure/cleanup faults retain the durable row and
hold subsequent processing. Recovery rechecks the same failure state, and the
publication gate rejects such rows even when both results exist. A product
quality failure with completed scoring remains a valid observation.

The separate education scorer may explicitly declare
`migration_contract.import_input="legacy-school.sqlite"`. Only that public raw
file is mounted read-only into `/inputs/existing-business`; its private target
database and oracle are not mounted at that input path. The existing music-store
default remains `initial-store.sqlite`. Unknown/escaping names and absent files
are rejected before Docker is invoked. This extension is prepared separately
and does not change the frozen four-slot music-store technical cohort.

## Fixed live campaign outcome

The frozen live plan at integration HEAD
`e792f643c33f4c3100e6d52b4bfbfc5d257f23f2` is retained in
`runs/_tl03a/plan.json` (SHA256
`a93388c71950ca9c2eb551ba461e33869f3e3d13469af76e9b9fe37df098a7a5`).
The finite campaign stopped after two of four maximum dispatches. Explore and
preload both completed implementation, confirmed owned stop/network cleanup,
retained stopped raw/snapshot receipts, and reported complete usage:

| Serial Run | Implementation seconds | Calls | Reported total tokens |
| --- | ---: | ---: | ---: |
| MS1-CONT-A-explore-9001 | 932.562 | 84 | 4,379,390 |
| MS1-CONT-A-preload-9001 | 738.615 | 61 | 4,922,510 |

The first ordinary scorer returned `evaluator_fault`: the browser collector
could not load the host `playwright` module. The durable failed scoring/result
was preserved, subsequent processing was held, and neither paired slot was
dispatched. No model retry, replacement or additional trial was made. Preload
remains unscored in the original campaign. `runs/_tl03a/result.json` has SHA256
`53f77d26a5c862591dc41add5eac51b69110230f90363ab1d126ac099db5a11c`.
`owned-stop-proof.json` confirms no owned running worker/gateway or remaining
network; original stopped containers and all Run directories are retained.

Serial implementation makespan was 1675.581535 seconds; the partial local
block including its first failed postprocessing was 1720.881566 seconds.
Peak observed HTTP concurrency was two within the serial Run regime; Run
concurrency and native HTTP concurrency are separate measurements. Paired
elapsed improvement and distribution equivalence are unmeasured. External
publication time/acceptance remains `not_run`. This campaign does not complete
#20 and cannot justify paired scientific adoption. It is retained separately
from both historical data and the prospective study.

`image-equivalence.json` binds the original mock and live worker/gateway image
identities: all filesystem layers and runtime config (including in-memory Env
equality) match. Changed image IDs are retained as metadata differences; no Env
values or Env hashes were recorded. Thus the ordinary-worker serialization
proof is reusable without another passing mock/model attempt.

## Stage clocks after the frozen campaign

The separate subsequent implementation adds `postprocess-timing.jsonl`:
scoring, monitor import including any build, and archive packaging including
compression (or existing archive verification) each have their own durable
start/terminal clock. Run/instance/assignment identities bind each event. An
existing scoring result is retained and recorded as reused with duration
`null`; missing clocks are never synthesized as zero. Terminal rows bind the
timing receipt SHA256. These clocks do not retroactively measure the failed
live campaign and do not change its implementation budget.

`machine.timed_stage(receipt, stage, operation, binding=...)` also clocks the
ordinary local-public-gate adapter with plan/cohort/pair/instance bindings.
It records only exception type on failure, retains the started event, and
does not record arguments or returned payloads. Publication, independent
download/restore, socket-blocked extraction and owned cleanup still require
the actual normal gate receipts; a clock cannot satisfy that gate.

Stop reconciliation preserves the original unconfirmed implementation receipt
and creates a new final raw/manifest/snapshot hash binding, referencing the
original receipt by path and SHA256. The reader rejects a changed baseline.

The subsequent technical CLI requires a verified browser probe before cohort
allocation, captures its dependency/Node/browser/collector hashes in the plan,
and checks them again before dispatch. Only serial postprocessing activates the
validated browser paths and pinned Node using
`catalog_environment.activated(record, repo)`; the previous process environment
is restored on success or failure. The generic child environment remains
restricted. This correction does not authorize reopening the failed campaign,
resending either assigned instance or adding replacement model trials.

New source acquisition invokes Git archive with invocation-local
`core.autocrlf=false` and `core.eol=lf`, records that byte basis/configuration,
and leaves existing caches unchanged. The finite control uses a local Git
fixture whose cache is deliberately configured for CRLF, then verifies the
production archive retains the committed LF bytes without persistent settings.
