# MS1 catalog: proposed post-start date comparison amendment

The bounded repair and offline verification are complete. **The experiment is
still paused. This proposal has not been adopted or approved for resumption.**
No new model request, resend, reevaluation, release or actual recovery was
performed during this work. The implementation authority is the user's instruction
“初回Runの日付差分による停止への限定対応”, limited to repair, offline checks and
saving the proposal. Its reference is retained in
`artifacts/catalog-date-revision-20260923/implementation-authorization.json`.

## Approval targets and post-start timing

| Record | SHA-256 |
| --- | --- |
| Original [r2 plan](../research/protocols/ms1-catalog-comparison-v2-execution-20260922-r2.json) | `14622f31c510607c8999026fe2fa308630ce6bb528bcfeb6667b3d46c349ea9b` |
| Proposed [r3 plan](../research/protocols/ms1-catalog-comparison-v2-execution-20260923-r3.json) | `8bbe1301bf4cb5d81baa0688c5c643300fb1a463c82f213082a09d605bff9ca6` |
| [Post-start amendment](../research/protocols/ms1-catalog-date-revision-20260923.json) | `a97e4c3a8c338e23251782a336d1d4926ad03b62bfd574081908f840877c3694` |

The proposal was recorded at **2026-09-22 17:41:40.208080 UTC** (September 23
in Japan), after the first result had been seen. The first dispatch was at
13:34:35.340879 UTC; its terminal result was recorded at 13:51:09.676433 UTC.
The date-only pause at 13:51:09.677900 UTC remains in the original journal.
The amendment carries both complete code-hash maps, the old receipt/approval/seal
hashes and the exact original journal checkpoint.

`MS1-001-catalog-expanded-1001` was acquired under r2. The revised comparison will
apply uniformly to that retained Run and every later allocated Run after explicit
adoption. It is not a pilot, replacement or newly acquired r3 Run. The allocation
remains **320 pairs / 640 slots**, with 1 dispatched, 1 terminal, 639 undispatched
and 0 uncertain. Slot 2, `MS1-001-catalog-compact-1001`, is the next unsent slot.

Only the status, affected code pins and explicit amendment metadata differ in the
plan. The exact allocation, seed, model/agent/task, request generation, available
files/retrieval, timeouts, concurrency, evaluator, missingness rules, estimands
and interval methods remain unchanged. `launch.authorized=false` remains unchanged.
The original launch receipt retains its original r2 code hashes.

## Original difference and comparison rule

Both saved first requests match their recorded hashes:

| Saved request | Original file SHA-256 |
| --- | --- |
| Baseline expanded-001, `fcc0567aac8d4763af51dd0074b86c83.request.json` | `5fd4110515b1685a6fe7a10d86a9eb36f829c92367bc01ef8d5fc4de0681165c` |
| Acquired expanded-1001, `cbbc035894ba4f9ca1508c29c21f66a3.request.json` | `292f1b2ee939062f117663aabd22c8d6fe46d07edb2c61b93124b3d0884f5b5c` |

After the inherited intervention-packet transformation, the only differing JSON
path is `/messages/0/content`. A separate literal replacement proves that the
entire remaining difference is the environment field changing from
`Today's date: Sun Sep 20 2026` to `Today's date: Tue Sep 22 2026`.
Task-prompt bytes, other system instructions, other messages, tool definitions,
request parameters, source-packet bytes and file-access receipts match.

The pinned [OpenCode 1.17.11 source, lines 61–68](https://raw.githubusercontent.com/anomalyco/opencode/v1.17.11/packages/opencode/src/session/system.ts)
constructs this environment block and generates the field with
`new Date().toDateString()`. The fetched source is retained locally with SHA-256
`0ae8028c3b6b972f990d34f290dad3a0b631651a812c68826e6415902ac1fb6d`.
The fixed runtime and retained manifest identify OpenCode 1.17.11.

`catalog_identity.py` validates one leading string system message, one exact
ordered environment block, one date field in its expected position, the English
date format and calendar/weekday agreement. It replaces only that date span on
a deep copy. Missing/duplicate/moved/malformed fields fail. Other system text and
all user/tool/source text remain visible to comparison. Changes to the source
packet or access receipt also fail even if packet removal would hide them.
An absent initial request remains unobserved (`null`), never a match or zero usage.

The saved audit records the original dates and **raw common inequality** separately
from **normalized equality**. Original request-file hashes are separate from the
sorted compact UTF-8 JSON comparison hashes. The common objects have hashes
`af38a9fd86653ccce910356021ddd4e4ae1f24d012f7553d190745b33b4359e3`
(actual) and `0197414d17977aa1707ad2cb4d34b3afa633efda84b1cec81248c1cc910d8297`
(baseline); both normalized objects hash to
`dbe54d47a52f380c5a7059b0a07669539d325e21e204e185ce236350c2cd84dd`.
No transmitted request, saved request, baseline, OS clock or OpenCode binary was edited.

## Implementation and lineage

| Files | Purpose |
| --- | --- |
| `research/catalog_identity.py` (new) | Shared strict comparison and distinct raw/normalized audit fields. |
| `research/catalog_date_revision.py` (new) | One bounded r2-to-r3 proposal, later approval/adoption, original-record and amendment-history verification. |
| `research/catalog_pilot.py`, `research/catalog_execution.py` | Stop assessment and terminal comparison evidence; validated amendment use in the existing batch. |
| `research/catalog_observations.py`, `research/catalog_confirmatory.py` | Same comparison, preserved old receipt and amendment lineage; independent raw-evidence recomputation before analysis. Statistics unchanged. |
| `research/catalog_share.py` | Include the required old/new records and pinned comparison code in future public copies; verify the same comparison/history on offline extraction. |
| Two new test modules and `research/tests/test_catalog_confirmatory.py` | Date and amendment regressions; immutable historical pins checked against r2, current changed pins against r3. |

The execution code map pins 43 files, including both new shared modules. Existing
model/harness/evaluator code and runtime pins are unchanged. The proposal validator
rejects changes outside the five named existing code files and two added files,
any scientific-plan change, and any mismatch between saved plan, amendment and
current file hashes. Adoption requires a later user approval binding **both** new
hashes. Execution, observation/analysis and sharing require that adoption and its
journal event. Missing, duplicate, altered or unknown revision history is rejected.

The existing public-copy procedure redacts the machine-local home prefix in the
journal's terminal seal path. Local lineage validation therefore requires the
exact original journal byte-prefix hash; public validation verifies an explicitly
named projection hash where only that path is made repository-relative. These
digests are not interchangeable. Public copies retain the approved reference to
the raw journal hash and the unchanged original launch receipt.

## Verification and preservation

Final tests used the fixed Python 3.14.4 and `-B`:

| Suite | Result | Log under `artifacts/catalog-date-revision-20260923/` |
| --- | --- | --- |
| Date/lineage regression | 29 / 29 pass | `tests-date-revision-final-v4.log` |
| Entire research suite, including those 29 | 171 / 171 pass | `tests-research-final-v3.log` |
| Existing harness suite | 154 / 154 pass | `tests-harness-final-v3.log` |

The final suites cover 325 tests; the focused 29 are not added again to that total.
Checks include same/different day, month/year boundaries and leap day; non-date
mutations; dates outside the system environment; malformed/missing dates; raw vs
normalized evidence; terminal/observer/analyzer agreement; unchanged old receipt;
tampered/unapproved/missing lineage; preserved failures/missing requests; and
simulated recovery with **only compact-1001 dispatched**.

Revision tests use private synthetic repositories. Real journal, comparison,
proposal/adoption/recovery, observation, analysis, public staging and relocated
offline-reader paths are exercised there. Model dispatch, environment/profile
verification, generated evaluation data and resource operations are mocked or
synthetic. Existing suites use local fixtures/stubs for provider, Docker and GitHub
boundaries. The relocated extractor runs with networking blocked. This is not a
claim of live resumption, product reevaluation, or actual Release round-trip success.

The real saved requests and Run were read through the production comparison,
assessment and observation readers, without executing a model or evaluator.
Legacy assessment still reports `initial_request_differs_from_probe`; the proposed
rule reports a match. This read-only audit does not clear the actual pause and is
not an adopted confirmatory analysis.

All **663 original Run files**, including request/response/evaluation evidence,
match the pre-edit inventory. The original archive and its references verify.
The r2 plan, old approval, frozen plan, launch receipt, seal and all five journal
events remain byte-identical. No adoption receipt or compact-1001 directory exists.
No recompression, deletion or archive recreation was performed.

The retained measurement remains 4,763,249 input + 49,682 output = 4,812,931 tokens
across 65 requests in one Run. Primary totals are complete; the saved unknown
cache-write count remains null. The saved evaluator 1.2.0 result remains 93.1,
verdict fail (R-014/R-015), with human review not run. These are readbacks of the
original result, not new scores or evidence of study success.

The final offline `check` passed fixed pins and storage prerequisites at
2026-09-22 17:41:41.850486 UTC. Its legacy field `ready_for_start_approval=true`
does not authorize this amendment: `may_start_pair=false` and the approval blocker
remain. Original r2 execution is also rejected by the changed current code pins.

Earlier unsuccessful checks and intermediate candidates were retained. The first
142-test research run failed one obsolete historical-current-hash assertion; a
later 29-test run had one incorrect test output-key lookup. Both were corrected
before the final green runs. Intermediate 22/26/27/28-test and 169/170-test results
are distinct attempts, not additional coverage. Two unapproved proposal drafts
are retained under `draft-001/` and `draft-002/`; their hashes are not approval targets.

The [machine-readable readiness record](../research/design-results/catalog-date-revision-readiness-20260923.json)
contains the test-attempt ledger and evidence hashes. Detailed local evidence:

- `artifacts/catalog-date-revision-20260923/saved-request-audit-final.json`
- `artifacts/catalog-date-revision-20260923/saved-run-observation-revised-rule-final.json`
- `artifacts/catalog-date-revision-20260923/preservation-before.json`
- `artifacts/catalog-date-revision-20260923/preservation-after.json`
- `artifacts/catalog-date-revision-20260923/proposal-preflight-final-v3.json`

## Application and resumption after a later explicit approval

These steps are **not executed by this repair**. Keep the existing batch. Never
edit r2, the old approval/receipt/seal or the old journal prefix.

1. Obtain the user's explicit approval of the exact r3 plan and amendment hashes
   above. Record it in a new file using the existing `write_new` function, with
   `authorized=true`, `approved_by="user"`, both `plan_sha256` and
   `amendment_sha256`, the actual `approved_at_utc`, and a genuine
   `authorization_reference`. Do not reuse the earlier implementation-only
   instruction as adoption approval or rewrite the old start approval.
2. Run a fresh `check` with r3 and a new output path. Validate its saved SHA and
   reasons. Invoke the bounded adoption command using the new approval. It verifies
   r2 provenance and writes only the additional adoption receipt and journal event;
   the original pause remains. Repeated adoption reconciles that same record.
3. Check actual current pins, physical capacity, owned process/resource state and
   the saved-request comparison. Save real recovery evidence bound to the r3 SHA
   and the **post-adoption current journal SHA**. Include `verified`,
   `owned_resources_reconciled`, `api_or_environment_recovered`, a factual
   `explanation`, and `evidence_files` containing actual proof hashes. No reexecution
   or reevaluation is needed for this date mismatch. If authorized cleanup appends
   evidence, declare its actual `operations` under the existing recovery rules.
4. Use the existing `recover`; do not clear the pause manually. Then call `execute`
   once with r3 and the same new approval. It advances only the remaining slot of
   pair 1: compact-1001. Expanded-1001 remains the acquired r2 slot. Complete the
   existing exact-inventory public review, sharing, independent download, restore
   and extraction checks before starting pair 2.

Future commands, after the approval and actual evidence above exist (variables
name real new files chosen at that time):

```powershell
$Python = 'artifacts/catalog-confirmatory-design/analysis-env/Scripts/python.exe'
$Plan = 'research/protocols/ms1-catalog-comparison-v2-execution-20260923-r3.json'
& $Python -B -m research.catalog_execution check --plan $Plan --out $PreflightPath
& $Python -B -m research.catalog_execution adopt-date-revision --plan $Plan --approval $ApprovalPath
& $Python -B -m research.catalog_execution recover --plan $Plan --evidence $RecoveryPath
& $Python -B -m research.catalog_execution execute --plan $Plan --approval $ApprovalPath
```

Each command's saved result must be checked before the next step. The existing
[execution/recovery/share procedure](ms1-catalog-execution-ready.md) and
[recovery contract](../research/design-results/catalog-recovery-readiness-20260922.json)
continue to apply. Evaluation recovery still needs its own separate approval.
