# The first pilot pair was published, downloaded and extracted offline

Subsequent preparation: [the fixed 320-pair execution plan and driver](ms1-catalog-execution-ready.md)
supersede this rehearsal's remaining implementation/freeze items. Its historical
evidence below is preserved. The real experiment remains unstarted and requires
separate approval of the frozen plan.

The [public Release](https://github.com/fukuda-yuki/sample2/releases/tag/catalog-pilot-sharing-20260922)
contains a bounded subset of the existing technical pilot. Its four assets were
downloaded through anonymous HTTPS into a different directory; all local and
GitHub SHA-256 values matched. Restoring the ZIP verified **464 files**. Running
the bundled Python reader from that restored directory, with Python socket
operations blocked, reproduced the pre-upload extraction **byte for byte**.

The [machine-readable evidence and asset index](../research/design-results/catalog-sharing-validation-20260922.json)
records release/asset IDs, URLs, sizes, hashes, tests, failed attempts and limits.
**This establishes the small sharing route, not experiment readiness.** The
active v2 plan still has no N or allocation and `launch.authorized=false`.
No model, evaluator or historical rejudgment was run. PR #16 remains merged;
its Testing section was corrected and read back without altering the merge.

## What the public subset contains

Selection is the first randomized pilot pair, by slot order: compact-001 and
expanded-001. Both original conditions are present. Two sealed gateway SQLite
files reproduce **81 requests**. All **three evaluation attempts** are retained:
the compact Run's initial evaluator fault, its failing adopted evaluation, and
the expanded Run's adopted evaluation. Nothing was regenerated or rescored.

The archive is **6,634,495 bytes (6.33 MiB)**. It contains request JSON/response
SSE, native agent events/tool operations, prompts/catalog inputs, frozen products,
evaluation results, browser/HTTP evidence, PNGs/traces and a standard-library
reader. It needs one ZIP part; all four Release assets are below 1 GiB.
The tag anchors accepted base `b005f55`; the exact newly added reader bytes are
embedded and hashed in the bundle. It is not an execution-plan freeze.
The Release notes also provide a tested bootstrap using only the downloaded ZIP
and its manifest; it restored all 464 files without the unpublished checkout.
The new code/index commits remain local because automatic approval review denied
Git push. No new PR or CI is claimed; the public data assets are already available.

`MANIFEST.json` enumerates the selected Runs' **1,424 original files**, included
public hashes, **972 exclusions**, and **34 transformed files**. All 1,424 original
files were rehashed after the real round trip and remained unchanged. Local home
paths were replaced only in public text/trace copies. Original gateway DBs, raw
provider bodies/streams and frozen products retain their recorded byte hashes.

The [bundle README](../research/sharing/README.md) explains offline extraction;
the [license and exclusion notice](../research/sharing/THIRD-PARTY-NOTICES.md)
identifies Ms-PL and OpenCode MIT material and supplies full license texts.
Runtime binaries, most upstream legacy inputs, native auth/state caches,
evaluation DBs/WALs and duplicate workspaces/archives are omitted. Consequently,
this subset does not reproduce full native-state inspection, evaluation-DB
queries or the complete original execution environment. No project-wide reuse
license was invented. Future full-corpus publication still needs the applicable
dependency and public-copy review; this rehearsal does not approve it wholesale.

## Local storage: actual small round trip and explicit staging estimate

The public directory occupies **49,167,555 bytes**. Holding public copy, ZIP,
downloaded ZIP and restored directory simultaneously used **111,604,100 logical
bytes (106.43 MiB)**, excluding small receipts and QA contact sheets. The real
copy/package/download/restore writes all succeeded. C: also contains the host
temporary directory and observed Docker WSL VHDX files. No container was started.

At the recorded readiness check, C: had **302,372,446,208 bytes (281.61 GiB)**
free. The existing four-Run retained cohort still occupied **1,855,399,176 bytes**;
its 640-Run proportional reference remains **276.48 GiB**. The earlier 286.37 GiB
snapshot is not a current free-space promise.

The concrete operating proposal is to stage **at most one adjacent pair** at a
time. Preserve originals; after successful remote readback and offline restore,
remove only owned temporary public/download/restore copies whose identities and
hashes have been verified. Uploading by itself never counts as reclaimed space.
Never batch-copy all 640 Runs into an additional local public corpus.

After this verified round trip, the three task-created staging public copies
were removed (**147,479,492 logical bytes**). Their scan/stage receipts, archive,
download and restored corpus were retained. The original 1,424 files were
rehashed once more after cleanup and still matched. The cleanup receipt records
actual free-space readings separately because other host activity can change them.

The admission record explicitly counts next-pair retained growth, generation
scratch, SQLite finalization, public copy, archive, download and restored copy.
The current pilot-based temporary reference is **4,294,567,204 bytes (4.00 GiB)**:
one half of full pilot retention per pair, twice the largest saved Run directory for
scratch, sealed DB finalization and ZIP overhead. With the complete 640-Run
retention reference, only **1.13 GiB** remains at this disk snapshot. This is a
forecast, not an upper bound: future trace/state growth, Docker growth and other
host writes can exceed it. Keep the user reserve at zero, but re-read actual free
space before each pair and halt new dispatch if the explicit reservation does
not fit. Full-study storage capacity is not certified by the 106 MiB rehearsal.

## Pair-start rule after the user's no-overage clarification

The [proposed admission record](../research/design-results/catalog-pair-admission-20260922.json)
and [offline decision helper](../research/catalog_admission.py) apply the user's
2026-09-22 clarification: **paid overage is disabled; exhausting the allowance
only makes the API unavailable. Monetary-limit verification is not a start
condition.** This is user-confirmed account policy, not a claim of independent
Console inspection. No repeated setting confirmation or paid capacity is needed.

The earlier dollar-reservation rule was an unnecessary added constraint and is
superseded. The [correction receipt](../research/design-results/catalog-admission-policy-validation-20260922.json)
records this change separately from the original sharing-validation snapshot.
The current record still returns `may_start_pair=false`. This helper never dispatches
a Run and has not been integrated into the acquisition controller.

From the repository root, save a fresh decision to an absent output path:

```powershell
python -B -m research.catalog_admission --record research/design-results/catalog-pair-admission-20260922.json --out new-admission-decision.json
```

Exit code **2** means held; the written JSON explains every blocking reason.
The saved disk evidence is a snapshot and must be refreshed for actual dispatch.

1. Do not require monetary caps, prices, a dollar reserve for two Runs, proof of
   exclusive account use, or completion before a reset/promotional expiry.
   Usage percentages and reset times, when available, help schedule waiting;
   a successful fresh usage GET is not itself a prerequisite. A pair may exhaust
   the allowance before both Runs finish; completion is not guaranteed.
2. On known API unavailability or a quota/rate-limit response, record the failure
   and set `api_recovery_pending=true`; stop new dispatch and wait for recovery.
   The offline helper takes this state from the caller; it does not observe or
   retry the API. Clear the pause only after recovery and dispatch reconciliation,
   not merely because a predicted reset passed. Preserve the same provider/model,
   allocated slots and any partial/uncertain work. Recovery does not authorize a
   replacement Run, skipping to a new pair, or replaying an uncertain call.
3. Require a disk readback no older than five minutes and enough physical space
   for all seven stated storage components. Stop new dispatch on storage failure.
   User discretionary reserve remains zero; uploads alone free no local space.
4. A successful resource calculation is insufficient by itself: a fixed execution
   plan with its allocation/pins and separate start authorization are still
   required. Nothing in this helper grants either.

The historical account GET at **2026-09-22 15:13:58 JST** returned rolling **0%**, weekly
**0%**, monthly **14%** used. Reset timestamps were respectively **20:13:57 JST**,
**September 28 09:00 JST**, and **October 9 12:46:44 JST**. All statuses were `ok`.
These observations are retained as context, not a claim of present API availability
or a required dollar calculation. The later user confirmation resolves the
no-overage policy; no further account query or model request was made for this fix.

## Validation and remaining acceptance

The original sharing rehearsal passed **22/22**: 12 sharing/admission checks and
the prior 10 allocation checks. Earlier 20- and 21-test passes are separately
recorded, not added together. Its read-only four-DB check reconciled 218 request
spans without source changes. The correction receipt records the subsequent test
run independently; those four DBs and the older 91-test suite were not rerun for
the policy correction.

The initial public scan found home paths inside four trace ZIPs; a second copy
fixed them. Final scanning covered all 464 files, SQLite text/BLOBs, decompressed
ZIP members and the existing provider credential without logging its value.
Agent visual review covered 12 saved PNGs and 36 trace JPEG frames. This is
privacy/packaging inspection, not human product acceptance or re-evaluation.

Two failures are retained separately: the first offline extraction wrapper broke
Python's SSL class import by replacing `socket.socket`; using an audit hook then
passed with unchanged bundle bytes. The first admission-record construction
exposed an unhandled null terms timestamp, fixed in that rehearsal. Terms expiry
is no longer an admission input after the policy correction; disk timestamp
validation remains covered. Neither failure dispatched a model/evaluator.

Remaining work is the physical storage and recovery procedure at the actual
acquisition path, and review of the full future sharing set's required inputs.
Then fix formal N, save the exact allocation,
plan/code/environment hashes and real pre-dispatch evidence, and obtain separate
experiment start approval. **N, 640 execution slots and launch remain unset.**
