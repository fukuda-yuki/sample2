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
python outer/verify/technical-pair-live.py --mode prepare --repo <integrated-repo> --out <new-technical-cohort> --mock-receipt <mock-result.json>
```

The corresponding `--mode execute` is exclusively the predeclared technical
test, using the existing Windows User credential through gateway stdin. It is
not a new-study command and cannot resume the old catalog cohort.
