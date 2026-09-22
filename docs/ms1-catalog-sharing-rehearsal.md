# The first pilot pair was published, downloaded and extracted offline

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

## Concrete pair-start rule, still awaiting account evidence and adoption

The [proposed admission record](../research/design-results/catalog-pair-admission-20260922.json)
and [offline decision helper](../research/catalog_admission.py) leave unknowns
unknown and currently return `may_start_pair=false`. This helper never dispatches
a Run and has not been integrated into the acquisition controller.

From the repository root, save a fresh decision to an absent output path:

```powershell
python -B -m research.catalog_admission --record research/design-results/catalog-pair-admission-20260922.json --out new-admission-decision.json
```

Exit code **2** means held; the written JSON explains every blocking reason.
The saved account/disk evidence is historical and must not be reused for dispatch.

1. Immediately before a pair, obtain a successful usage GET and disk readback
   no older than five minutes. Record the actual account's rolling/weekly/monthly
   monetary limits, their effective period, current rates, no paid overage, and
   whether other account consumers could consume the reservation. Public
   promotional terms alone do not verify those account fields.
2. Require all three windows to be `ok`. The official
   [usage route](https://github.com/anomalyco/opencode/blob/dev/packages/console/app/src/routes/zen/go/v1/usage.ts)
   returns status, integer percent and reset time; the
   [calculation floors the percent](https://github.com/anomalyco/opencode/blob/dev/packages/console/core/src/subscription.ts).
   For an actual monetary limit `L` and returned percent `p`, use the conservative
   remaining amount `L * max(0, 99-p) / 100`. A displayed 0% is not assumed zero.
3. Reserve both members before starting either. The proposed fixed reference is
   **$2.8837356 equivalent**: twice the largest saved pilot Run, repriced at the
   accepted peak input/output rates with no cache discount. The four saved values
   are $0.6817458, $0.8742108, $0.9711930 and $1.4418678. Every window's conservative
   remainder must cover the two-Run reservation. This is a prospective planning
   rule, not a charge prediction, spending cap or guaranteed maximum; do not
   change it in response to comparison outcomes.
4. Do not assume a future reset or promotional carryover. Use a two-hour planning
   horizon (the two existing 1,800-second generation budgets plus one hour for
   operations); if a window/term expires inside it, wait and read back again.
   This horizon changes neither the Run timeout nor the fixed N.
5. Require the measured local free space to cover every stated storage component.
   Pause between pairs for staged publication or quota resets. If an unexpected
   limit/storage failure occurs inside a pair, preserve partial/uncertain work
   and reconcile dispatch before continuation. Do not replace a Run, skip to a
   new pair, switch models/accounts, purchase capacity or replay uncertain calls.
6. A successful resource calculation is insufficient by itself: a fixed execution
   plan with its allocation/pins and separate start authorization are still
   required. Nothing in this helper grants either.

The fresh account GET at **2026-09-22 15:13:58 JST** returned rolling **0%**, weekly
**0%**, monthly **14%** used. Reset timestamps were respectively **20:13:57 JST**,
**September 28 09:00 JST**, and **October 9 12:46:44 JST**. All statuses were `ok`.
The API supplies no monetary limit or overage setting; Console was a login page.
Those fields remain unverified. The saved readback is already too old for actual
dispatch, deliberately producing an additional stale-evidence blocker.

## Validation and remaining acceptance

The latest focused test run passed **22/22**: 12 new sharing/admission checks and
the prior 10 allocation checks rerun now. Earlier 20- and 21-test passes are separately
recorded, not added together. The older 91-test suite was not rerun. A new actual
read-only four-DB check reconciled 218 request spans without source changes.

The initial public scan found home paths inside four trace ZIPs; a second copy
fixed them. Final scanning covered all 464 files, SQLite text/BLOBs, decompressed
ZIP members and the existing provider credential without logging its value.
Agent visual review covered 12 saved PNGs and 36 trace JPEG frames. This is
privacy/packaging inspection, not human product acceptance or re-evaluation.

Two failures are retained separately: the first offline extraction wrapper broke
Python's SSL class import by replacing `socket.socket`; using an audit hook then
passed with unchanged bundle bytes. The first admission-record construction
exposed an unhandled null terms timestamp; the helper now rejects unknown dates
and a regression test covers them. Neither failure dispatched a model/evaluator.

Remaining work is account-specific capacity/overage evidence, acceptance of the
explicit two-Run and storage reservations, and review of the full future sharing
set's required inputs. Only then fix formal N, save the exact allocation,
plan/code/environment hashes and real pre-dispatch evidence, and obtain separate
experiment start approval. **N, 640 execution slots and launch remain unset.**
