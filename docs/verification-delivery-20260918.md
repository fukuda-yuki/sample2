# Verification-machine delivery, 2026-09-18

The approved local delivery gates passed: three interventions were each executed
twice with the real `deepseek-v4.1-flash` model, all six Runs completed through
collection, evaluation, monitor readback and preservation, and a restored artifact
was rescored without calling a model. All six generated implementations passed
all 29 requirements; implementation quality is separate from harness health.

The Linux engine was available when work resumed and ran the actual preparation,
fault controls and acquisitions. Docker reports Linux engine 29.4.1. Recovery
was confirmed through operation; no host-repair action was performed in this
continuation. The operating guide includes concrete Desktop restart and
switch-to-Linux instructions if recovery is needed again.

This is a local delivery on `codex/verification-machine`. No GitHub push, PR,
Issue mutation or Issue closure is claimed. [Issue #6](https://github.com/fukuda-yuki/sample2/issues/6)
remains the remote acceptance record; its seven items are mapped below.

## Start here

- [Operating and recovery guide](verification-machine.md)
- [Task-registration template](../outer/templates/task/README.md)
- [Portable delivery index](../artifacts/delivery/20260918-92cfb48-3830c217/delivery.json)
- [Six-Run acceptance result](../runs/acceptance-64ad09cd85ca/acceptance-result.json)
- [Independent original-data audit](../artifacts/delivery/20260918-92cfb48-3830c217/audit/audit.json)

The CLI supports preset inventory/detail, preparation, create/start/stop/status,
one-command execution, scoring/rescoring, aggregation/comparison and verified
package restoration. `--task`, `--intervention` and `--runtime` select independent
profiles. Inputs, profile originals, resolved conditions and hashes are frozen
when a Run is created. Existing schema 1 Runs remain readable.

## Fixed acquisition conditions

Acquisition source: `92cfb48a894ed8e35625072098c71d2a67aa2930`. The delivered code
uses the same acquisition/evaluation logic; subsequent report changes do not
alter these frozen Runs. The source ZIP and image export are accompanied by
SHA-256 receipts in the delivery index.

| Setting | Value |
| --- | --- |
| Task | MS1-001; 29 published requirements, evaluation 1.2.0 |
| Source | `chack411/MVC-Music-Store`, commit `2967afb9d69488641df0d154e2ad5827a7820e71` |
| Model | `deepseek-v4.1-flash`, all main and auxiliary requests |
| Gateway endpoint | `https://opencode.ai/zen/go/v1/chat/completions` |
| Agent | OpenCode CLI 1.17.11; subagent/task tools disabled |
| Dependencies | .NET SDK 8.0.425; EF Core SQLite and Microsoft.Data.Sqlite 8.0.31 |
| Execution | Sequential; implementation controller budget 1800 seconds per Run |
| Request limits | Frozen 600-second request/header/chunk limit; controller still bounds total implementation time |
| Isolation | Worker on internal network; gateway is its only external path; evaluator on `--network none` |
| Credential | Windows User `OPENCODE_GO_API_KEY` read by bootstrap and piped only to gateway stdin |

The exact model ID was checked against the [official endpoint table](https://opencode.ai/docs/go/#endpoints),
the [public catalog](https://opencode.ai/zen/go/v1/models), and every retained
response in these Runs. The failed unauthenticated direct catalog fetch (HTTP
403) is retained separately and is not model-availability evidence.

Task request, source, ledger, evaluator and runtime were identical across the
three arms. Exploration added no initial context block; preload added 20 fixed
source blocks; explanation added one description of existing processing. Every
block was located in the first transmitted request and matched to its original.
An injected block establishes delivery, not model understanding.

## Real observations

| Run | Seconds | Calls / native steps | Initial blocks | Quality / verdict |
| --- | --- | --- | --- | --- |
| MS1-001-explore-001 | 412.412 | 62 / 62 | 0 | 100 / pass |
| MS1-001-preload-001 | 462.97 | 38 / 38 | 20 | 100 / pass |
| MS1-001-explained-001 | 420.248 | 45 / 45 | 1 | 100 / pass |
| MS1-001-explore-002 | 717.007 | 52 / 52 | 0 | 100 / pass |
| MS1-001-preload-002 | 535.255 | 54 / 54 | 20 | 100 / pass |
| MS1-001-explained-002 | 457.166 | 71 / 71 | 1 | 100 / pass |

There were 322 gateway calls in total, with matching durable start and
terminal records, original request/response hashes, expected model IDs and
dedicated monitor DB readbacks. The audit performed 1855 checks.
Every Run has its own globally unique instance and native session evidence.

| Run | Input | Output | Cache read | Reasoning | Cache write |
| --- | --- | --- | --- | --- | --- |
| MS1-001-explore-001 | 4,048,388 | 57,180 | 3,993,088 | 33,819 | null |
| MS1-001-preload-001 | 2,526,844 | 46,186 | 2,474,880 | 29,489 | null |
| MS1-001-explained-001 | 3,342,070 | 40,441 | 3,273,856 | 22,448 | null |
| MS1-001-explore-002 | 3,160,186 | 43,466 | 3,109,248 | 24,473 | null |
| MS1-001-preload-002 | 4,096,295 | 52,945 | 4,022,400 | 32,139 | null |
| MS1-001-explained-002 | 4,380,332 | 38,941 | 4,322,048 | 21,489 | null |

These are provider-reported counts, not a billing estimate. Cache-read counts
are a breakdown of input, and reasoning counts are a breakdown of output; do
not add those columns again. Cache-write usage was unreported and remains
`null`. `usage_complete` means complete call inventory and input/output
accounting; it does not make an unreported optional breakdown known.

Execution duration covers controller startup, implementation, drain and stop
confirmation. Preparation, evaluation and packaging are separately recorded
operations. The default 30-minute implementation budget was retained; these
small observations do not establish a universally sufficient budget.

| Run | Original workspace normalization |
| --- | --- |
| MS1-001-explore-001 | No source byte changes |
| MS1-001-preload-001 | No source byte changes |
| MS1-001-explained-001 | No source byte changes |
| MS1-001-explore-002 | No source byte changes |
| MS1-001-preload-002 | MvcMusicStoreModern.sln: bom_removed, crlf_to_lf |
| MS1-001-explained-002 | No source byte changes |

## Issue #6 evidence mapping

| Item | Status | Evidence and boundary |
| --- | --- | --- |
| 1. Actual agent startup, completion and stop, including timeout/children | Pass | Six real ordinary CLI Runs; fresh stopped-container readback in the audit. Ten Docker controls cover normal exit, deadline, operator stop, crashed-controller recovery, HTTP failure, missing usage, wrong model, truncated stream, slow stream and active-request cancellation. Fault injection uses a mock provider and synthetic credential. |
| 2. Actual usage originals and normalization | Pass | Per-Run `usage/raw/`, `usage/events.jsonl`, `usage/normalized.json`; input/output/cache/reasoning checked against all raw responses. Unknown cache-write values stay null. |
| 3. Complete request/session inventory | Pass | All 322 starts and ends reconcile to six unique instances; original hashes match; isolation preflights and fresh network readback pass; native sessions are distinct from gateway observation. |
| 4. Intervention reaches actual input | Pass | Each `usage/context-evidence.json` maps the original prompt and 0/20/1 additional blocks to first-request message/string locations. Numbered Read rendering checks consecutive lines; its unobservable final newline is explicitly noted. |
| 5. Real workspace line endings/BOM | Pass | Each `snapshot.json` retains original and normalized hashes and exact changed paths; original workspace bytes were checked and packaged. Observations are listed above. |
| 6. Empirical execution budget | Pass | All six use the same 1800-second controller budget and 600-second provider limits. Observed durations are listed above; synthetic timeout/slow-response controls test both boundaries. No intervention-effect or budget-optimization claim is made. |
| 7. Existing local-agent-monitor integration | Pass | Each dedicated `telemetry/monitor.db` was imported through the existing `ingest-raw`, normalized, and read back for identity, calls and counts. The receipt labels it gateway-derived, not native OpenCode telemetry. Partial-import controls verify observed sums independently from unknown Run totals. |

## Repairs established through execution

- Parsed equivalent XML and HTML semantically; comments and hidden/script text
  cannot provide required observations. Calibration includes an independently
  valid implementation and equivalent markup.
- Published evaluation 1.2.0 with an explicit completion DOM marker and
  cross-session HTTP behavior. Invalid checkout must preserve cart quantities,
  albums, total and stored order IDs. Old 1.1.0 Runs retain their original ledger.
- Corrected two observed R-029 false failures: a standard IIS Express launch
  profile and a modern Web SDK project retaining `MvcMusicStore.csproj` as its
  filename. Both unchanged artifacts were readjudicated under their original
  1.1.0 contract. Original scores and adjudications remain separate.
- Removed credential inheritance, tested isolation and stop recovery, preserved
  original streams and rejected inconsistent identifiers, duplicate/missing
  calls, model mismatches and modified frozen submissions.
- Fixed real Windows long-path preservation and repeated monitor ingestion.
  Changed prepared conditions no longer merge merely because preset names match;
  running/uncollected usage remains unknown instead of zero.
- A later real request stalled behind provider heartbeats. The former 120-second
  request cap expired while the 30-minute budget remained. Immediate gateway
  termination lost its terminal journal; a partial monitor sum was also compared
  with an unknown total. The repaired runtime freezes 600-second provider limits,
  cancels upstream sockets on graceful shutdown, records cancellation, and
  distinguishes observed partial sums from null totals. A 130-second queued
  mock response and active-request stop both passed. The previous five-Run
  attempt is retained as diagnosis, not combined with final acceptance.

There were eight actual model executions in the retained diagnostic cohorts,
in addition to the six final acceptance Runs. Two more diagnostic Run directories
were created but refused before model dispatch. They are not counted as real
model executions or silently dropped from their cohort records.

| Diagnostic cohort | Actual model executions | Original outcome and subsequent handling |
| --- | --- | --- |
| `acceptance-fed99de3acd5` | 1 | Quality 96.55 from the IIS Express R-029 false failure. Unchanged-artifact 1.1.0 adjudication passed: `runs/_adjudication-524f07205622/`. The next created Run was not dispatched. |
| `acceptance-f14a4f5ff874` | 2 | One quality 100; one 96.55 from the modern project filename R-029 false failure. Unchanged-artifact 1.1.0 adjudication passed: `runs/_adjudication-b89f23f88992/`. A third created Run was refused before dispatch when conditions changed. |
| `acceptance-ef3852b05955` | 5 | Four healthy Runs; the fifth artifact scored 100 but its agent timed out and call inventory/usage was incomplete. It failed machine acceptance. Originals, unknown totals and the failed monitor receipt are preserved. |

## Verification beyond the six Runs

| Verification | Result | Records |
| --- | --- | --- |
| Python regression suite | 120 tests passed | `artifacts/checks/2141a720ee284b13b40de90711a8b810/` |
| Evaluator regression assertions | 28 passed | `artifacts/dotnet-checks-f9bb6fdd123542419cd6d3b153c007fd.log` |
| Linux evaluator calibration | 34/34 exact expectations | `runs/_calibration/20260918T084425-ebef195b3072407f82244bd26fc4d861/` |
| Calibrated image equivalence | Worker and evaluator root filesystems, configs, OS and architecture identical | `runs/_runtime-equivalence-38a1dd995c3f/`; gateway intentionally changed and was tested separately |
| Docker lifecycle and provider controls | 10/10 | `runs/_container-probe-4e500fae6bfb/` |
| Actual monitor missingness controls | 3/3 | `runs/_monitor-missingness-11f045827a0b/` |
| Incomplete real-Run offline monitor replay | Passed; known totals match, authoritative totals null | `runs/_monitor-partial-replay-c483871334d1/` |
| Version/ledger mismatches | 2/2 refused with error/null quality | `runs/_version-mismatch-efecc452695a/` |
| Modified artifact and reused scoring sequence | 2/2 refused through ordinary CLI | `runs/_preserved-run-challenges-b89871975b0f/` |
| Contaminated evaluation work directory | Refused before executing application | `runs/_contaminated-evaluation-2c00745addf2/` |
| Exported Docker image reload | All three exact IDs matched | Delivery `image-roundtrip.json` |
| Fresh source directory and restored package replay | Same artifact, judgments, quality and usage; no model execution | Delivery `replay-result.json` and ordinary CLI logs |
| Generated application browser workflow | Home → Jazz → Worlds → cart (1, 8.99) → checkout → order 1; cart cleared; DB row retained; both preview containers stopped | `runs/_browser-check-31b874f750f4/result.json` and original app/proxy logs |

Calibration includes positive/reference and independent implementations, equivalent
markup, order retention, session isolation, invalid checkout mutations and
evaluator faults. A fixture success is evidence for the tested contract, not a
proof against every possible defective or adversarial program.

## Preservation and reproduction

The delivery archive contains the six original Run packages, pinned runtime
images and source, original diagnostic attempts, calibration/control evidence,
audit, browser observations and this report. Package references pin their index
hashes; verification checks file hashes and references. Failed diagnoses are
retained instead of deleted or overwritten. The delivery index lists exact
package hashes, file counts and reproduction commands.

Restore into a new directory, load the retained images, then use the extracted
source to run `restore`, `rescore` and `aggregate` with an explicit `--runs-dir`.
These paths do not read the model credential or invoke a model. The first Run
was replayed this way, independently of the automatic batch restoration, with
fresh work/database state and identical judgments. A changed artifact or reused
scoring output is refused.

## Limits and remaining scope

No required gate in this local delivery remains open. This machine is accepted
for the one published MS1-001 task; adding another profile requires its own
calibration and live validation. Two Runs per intervention support descriptive
observations only, not a statistical conclusion about intervention effects.

The 29 requirements do not assess full storefront visual fidelity, account or
administration features, deployment, general security or performance. Order
persistence observes the published `Orders.OrderId` contract, not every detail
row or `Order.Total`. The inspected generated application returned 404 for CSS
and album imagery, while its required transaction flow worked. Provider
internals, understanding and unreported usage details remain outside the
observation boundary. Broadening a
success criterion requires a new public request/ledger version before acquisition.

Raw results are local and Git-ignored. Remote publication/integration is not
part of the completion claim.
