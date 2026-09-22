# MS1 catalog comparison: fixed preparation, awaiting start approval

The three preparation tasks are implemented by
[`catalog_execution`](../research/catalog_execution.py),
[`catalog_delivery`](../research/catalog_delivery.py) and the bounded pair reader.
The [frozen execution plan](../research/protocols/ms1-catalog-comparison-v2-execution-20260922.json)
allocates **320 pairs / 640 Runs**, with the existing seed, one compact and one
expanded Run per adjacent pair, attempts 1001 through 1320 per condition.
The [preparation receipt](../research/design-results/catalog-execution-preparation-20260922.json)
records the exact plan/code/environment hashes and actual verification results.
**No experiment start approval or real dispatch is included in preparation.**

The prior unallocated v2 JSON and all earlier receipts remain historical and
unchanged. Scientific endpoints, inference, missingness, model, intervention,
timeouts and evaluator remain those of v2. There is no quality-loss margin,
replacement Run or outcome-dependent N. Six weeks is an initial operating
window; pauses can require more calendar time. Completion is not guaranteed.

## Execution and recovery

The driver calls the ordinary harness CLI. Before each slot it checks the frozen
profiles, source inventory, evaluator bundle, controller, Docker images, Python,
analysis packages and browser dependencies, plus actual free disk space. A
separate user approval must bind the exact plan SHA-256. The immutable plan's
`launch.authorized=false` records preparation-time status; the approved start is
recorded separately, without rewriting the plan or rerandomizing its slots.

An OS lock prevents concurrent drivers. A dispatch is flushed and fsynced before
the child process starts. A crash with no terminal record is uncertain, even
when no Run directory exists. It is never automatically replayed. A terminal
result retains its original-file inventory, failure, evaluation and archive
reference. Ordinary product failure does not select a replacement or stop the
study; resource, identity, environment or cleanup faults stop new dispatch.

API exhaustion pauses acquisition. Paid overage is disabled by user confirmation;
there is no monetary-limit check, dollar reservation, account rotation or model
fallback. Recovery requires evidence bound to the exact plan and current journal,
documented API/environment recovery and reconciliation of owned processes and
resources. Preserved results are rechecked. Only never-dispatched slots continue,
in their original order. An uncertain slot stays uncertain in the denominator.

`_control/launch-receipt.json` is created immediately before the first approved
dispatch and binds the fixed plan, analysis code, approval, checks and journal.
It does not exist for the unstarted real cohort. Source observations remain
separate from analysis, and missing usage remains unknown.

## Storage and pair publication

The per-pair physical check includes retained Run growth, generation scratch,
SQLite finalization, public copy, archive, download and restore. The inherited
pilot-based reference is **5,222,266,792 additional bytes**, with zero discretionary
reserve. Actual package/transfer checks also account for both split parts and
their assembled ZIP when needed. These are forecasts and current-space checks,
not upper bounds on future Run size or a guarantee of whole-study capacity.

Completed Run directories and their archive package closure use lossless NTFS
compression only after generation/evaluation has stopped and owned network
cleanup is confirmed. Live work directories are never pre-compressed by this
procedure. Every file hash and the archive references are checked before/after;
any compression failure holds further dispatch. Original bytes remain available.

The [actual owned-copy probe](../research/design-results/catalog-retention-validation-20260922.json)
covered all 6,098 files in the four-Run pilot: 1,855,399,176 logical bytes became
1,272,881,404 stored bytes. Archive restoration verified 589 files, and a separate
read-only check of four compressed SQLite copies retained all 218 requests.
The 640-Run stored reference plus one-pair temporary workspace is
207,955,591,844 bytes (**193.67 GiB**), within the checked C: capacity. This is an
observed pilot ratio, not a promised future compression ratio or size ceiling;
filesystem metadata is not included in the file-storage figure. Fresh free-space
checks and pause/recovery remain necessary. Only owned probe copies were removed.
The operation uses Microsoft's [compact](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/compact)
and measures file storage with [GetCompressedFileSizeW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getcompressedfilesizew).

After both members of a pair reach terminal records, the driver stages their
public evidence and waits. Missing directories, failed/unscored Runs and every
saved evaluation attempt remain visible. The complete 640-slot plan and dispatch
journal keep the denominator and pairing visible. Original files are retained.

The operator reviews the exact public inventory, secrets, screenshots, dependency
notices and exclusions. An approved review binds those bytes. `share` then:

1. Scans and packages only the reviewed copy, splitting into parts of at most
   1 GiB and checking the Release attachment count.
2. Publishes one pair per prerelease in `fukuda-yuki/sample2`. Existing assets are
   reconciled by name, size and SHA-256; nothing is clobbered after an uncertain
   write acknowledgment.
3. Downloads separately over anonymous HTTPS, checks every part and metadata
   hash, restores every member, and runs the downloaded reader with socket
   operations blocked. Its extraction must match the pre-upload extraction.
4. Rechecks originals and retains the distribution/review/restore receipts before
   deleting only owned temporary copies. Verified publication alone is never
   counted as freed local space. The next pair remains held until this finishes.

A durable delivery receipt permits completion after an interruption during
cleanup without republishing. Failed transfer attempts are retained for diagnosis.
Native state/auth caches, evaluation DB/WALs, runtime binaries and most upstream
legacy files remain excluded under the existing bounded sharing contract. This
limits native-state, DB-query and full environment replay; it does not remove
the locally preserved originals or silently turn missing evidence into success.
Future generated dependencies require review when they exist; no advance blanket
publication approval is claimed. This is a per-pair procedure, not a new all-Run DB.

## Commands after preparation

Use the pinned Python at
`artifacts/catalog-confirmatory-design/analysis-env/Scripts/python.exe` from the
repository root. A fresh check does not start a model:

```powershell
& 'artifacts/catalog-confirmatory-design/analysis-env/Scripts/python.exe' -B -m research.catalog_execution check --out fresh-preflight.json
```

Only after the user explicitly approves the presented plan, save the separate
approval with `authorized: true`, `approved_by: "user"`, its exact `plan_sha256`,
the approval's UTC time and the actual authorization reference. No such approval
was fabricated during preparation. Then use the same driver for first dispatch
and continuation:

```powershell
& 'artifacts/catalog-confirmatory-design/analysis-env/Scripts/python.exe' -B -m research.catalog_execution execute --approval start-approval.json
& 'artifacts/catalog-confirmatory-design/analysis-env/Scripts/python.exe' -B -m research.catalog_execution share --pair 1 --review reviewed-pair-001.json
```

`execute` handles at most the remaining slots of one adjacent pair per invocation.
Review/share that pair before invoking it again. A fault requires `recover
--evidence recovery.json`; waiting for an estimated reset alone does not clear it.
The recovery record includes `plan_sha256`, `journal_sha256`, `verified`,
`owned_resources_reconciled`, `api_or_environment_recovered`, `explanation` and
an `evidence_files` mapping of actual file paths to hashes. For uncertain dispatch,
`in_flight_processes_stopped` must also be confirmed. These are evidence attestations,
not a mechanism for inventing a successful Run or retrying a lost request.

## Verification boundary

Fault-injection tests use synthetic dispatch and controlled remote transport at
the two external boundaries; the journal, storage, packaging, restoration and
cleanup paths are the production implementations. Real existing pilot evidence
is also staged, scanned, downloaded and extracted without regenerating historical
archives or evaluating products. The receipt separates failures, reruns, current
tests and prior Release publication. New uploader mutations are tested through
controlled transport; no new live Release write is claimed for this preparation.

The final read-only host check is a snapshot. Fresh disk and identity checks run
again at actual dispatch. Only the separate experiment start approval remains a
user decision after a passing preparation receipt.
