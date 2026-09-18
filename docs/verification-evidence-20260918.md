# Verification checkpoint, 2026-09-18 JST

This is the historical checkpoint before Linux engine recovery and live
acquisition. See the [completed local delivery](verification-delivery-20260918.md)
for the later results; the unsuccessful preparation/recovery record below remains intact.

**Delivery is not complete. Real-model acceptance is 0/6.** No real model was
called in this implementation/verification session. The records below distinguish
the real evaluator and real OpenCode executable from synthetic provider responses.
The operating procedure is [verification-machine.md](verification-machine.md).

## Repairs made through execution and re-evaluation

- XML project discovery now parses XML; equivalent SDK quoting and inert comments
  do not fail static checks. HTML observations use an HTML parser, including
  entity decoding and nested text; comments/scripts/templates cannot supply values.
- Worker/evaluator/child process environments are explicit allowlists. Provider
  credentials enter only gateway stdin. The generated application child process
  was tested with synthetic secret canaries, not the user's key.
- Calibration/probe outputs use unique directories. Existing Runs, fixture output
  directories and verification records are no longer deleted or overwritten.
- A real Windows preservation failure exposed paths exceeding 260 characters.
  Package/restore operations now use extended Windows paths without changing
  system policy; long-path regression and ordinary preservation tests pass.
- The gateway persists request starts before dispatch and writes partial response
  bytes durably. Missing terminal records, duplicates, wrong identities, response
  model mismatches, malformed journals and transport failures invalidate coverage.
- OpenCode renders attached files as numbered Read output. An initial preload
  probe therefore failed the original verbatim matcher. The corrected mapper
  records exact consecutive source-line locations and rejects changed/missing
  lines. The failed probe remains alongside later successful probes.
- An initial monitor probe imported the same raw payload twice and normalized
  20/5 tokens as 40/10. The repaired link skips repeated ingestion and validates
  normalized identifier, count and token readback. The reproduction DB is retained.
- Stop recovery checks Run ownership and daemon availability. Repeating `stop`
  on a completed Run preserves its history. Unexpected evaluator exit codes cannot
  contribute an adopted quality score even if a success JSON exists.

## Measured evidence

Paths are relative to this checkout. Raw files remain ignored by Git.

| Check | Measured result | Original records |
| --- | --- | --- |
| Real evaluator calibration | 22/22 exact expected outcomes: two reference runs, two independently valid runs, ten negatives, six equivalent forms, two evaluator faults | `runs/_calibration/20260917T180447-33d1399ab2324f8fa041bd0dde62787d/` (plan, per-case files and summary) |
| Evaluator parser and child-process regressions | 13/13 assertions, including a real child process with synthetic secret canaries | `inner/evaluator/MusicStore.Evaluator.Tests/`; recorded final check output in the local checkpoint package |
| Final outer ordinary path | 18/18 checks; 111 Python tests; build/rebuild, actual app evaluation, mutation refusal, rescore, preservation/restore/aggregate, no app process leak | `runs/_verify/af7c467ebbc8479c961fee56898d4aa7/verification-summary.json`, command logs and cases journal; retained package/restore under `runs/_preservation/af7c467ebbc8/` |
| OpenCode + mock gateway, explore | Exit 0; one synthetic call; all 19 prompt lines in initial request | `runs/_agent-probe-035ed5baf6e6/result.json`, `agent.jsonl`, `raw/` |
| OpenCode + mock gateway, preload | Exit 0; one synthetic call; 929 prompt lines, 20 source blocks mapped | `runs/_agent-probe-8e5d1258bbb8/result.json`, `context.json`, `raw/` |
| OpenCode + mock gateway, explained | Exit 0; one synthetic call; 22 prompt lines, one explanation block mapped | `runs/_agent-probe-d1539d7ae0f4/result.json`, `context.json`, `raw/` |
| Retained failed preload mapping | OpenCode completed; the original matcher reported no mapped blocks | `runs/_agent-probe-7786fb4177f3/result.json` and original request |
| Monitor DB readback after repair | One request, input 20, output 5, matching Run ID; second link preserved those counts | `runs/_monitor-probe-52d3e31b4810/telemetry-link.json`, `telemetry/monitor.db`, `normalized-readback.json` |
| Retained duplicate-import reproduction | Two synthetic spans, input 40/output 10 from repeated import of a 20/5 request | `runs/_monitor-probe-7dbbe5778a22/telemetry/normalized-readback.json` |
| Normal preparation entry point | Docker info exceeded its 30-second timeout, before image construction or model dispatch | `artifacts/runtime/MS1-001/preparation/3f51374d12ff41e391767a89cf739482/failure.json` |

The final outer test output and checkpoint package reference are recorded in
`artifacts/checkpoints/`. The earlier successful and failed attempts above remain
separate; later verification does not rewrite them.

## Issue #6 mapping

[Issue #6](https://github.com/fukuda-yuki/sample2/issues/6) was read back as OPEN.
The user's approved plan has a stricter acceptance gate than its original text:
merely listing unverified items is insufficient to close the delivery.

| Item | Evidence now | Remaining live gate |
| --- | --- | --- |
| 1. Agent startup, completion and stop, including timeout/children | Real OpenCode against mock provider; owned-process and real evaluator lifecycle checks; container supervision/recovery implemented | Exercise ordinary, timeout, stop, crash and orphan cases in the actual containers |
| 2. Usage originals and cache/reasoning mapping | Original synthetic SSE/JSON and missingness regressions; separate optional fields | Confirm actual Go usage schema and missing fields in real responses |
| 3. Complete request/session inventory | Start/end reconciliation and negative tests; native session IDs distinguished; boundary probe implemented | Execute network boundary checks and account for all real auxiliary calls |
| 4. Intervention reaches actual input | Three real CLI/mock-provider probes, with mapped first-request originals | Repeat and verify all six real Runs |
| 5. Line endings/BOM in the worker | Existing CRLF/BOM normalization and unchanged artifact identity tests | Observe real generated workspaces and retained normalization records |
| 6. Budget | Frozen runtime default 1800 seconds; diagnostic and final settings separated | Measure durations under that common budget; no empirical tuning claim yet |
| 7. Existing local-agent-monitor integration | Actual importer and normalizer, dedicated SQLite DB, exact readback, duplicate-import fix | Run the same integration on real provider observations |

## Blocking condition and resumption

Docker Desktop failed while initializing its Inference manager at the
`dockerInference` Unix socket, reporting that the file could not be accessed.
The Linux engine did not become available; ordinary `prepare` independently
confirmed daemon unavailability. An automatic approval review rejected the
attempted recovery command that stopped Docker processes and retained/moved its
communication directory. The returned reason was only **blocked by policy**.
That recovery action was not executed or retried through a different tool.
Manual Docker Desktop recovery has been requested; no reset/data deletion is
required by this implementation.

After the Linux engine is available, use a clean committed checkout, run
`prepare --rebuild`, and first exercise non-model container fault cases. Then
run `acceptance`: three arms twice, stop/fix/retry on verifier faults, verify a
generated application's start/browse/cart/order workflow, and restore/rescore
the resulting schema 2 package in another directory. Those gates remain open.
Host mock results and reference-app success do not substitute for them.

## Limits

The current calibration covers the published 29-requirement MS1-001 contract at
evaluation version 1.1.0, not arbitrary modernization correctness. Order retention
checks `Orders.OrderId` row survival; full order-detail/total semantics, security,
performance, authentication, administration and deployment are outside that
contract. The task template is supplied; a second task is not validated. No
intervention-effect statistics are claimed. Docker image construction, isolation,
real Go requests, six-Run acceptance and schema 2 restored scoring are unverified.
