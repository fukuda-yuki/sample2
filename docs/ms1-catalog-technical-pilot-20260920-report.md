# Catalog technical pilot — 2026-09-20

**Connection verification complete.** Both adopted conditions ran through the
normal generation, measurement, browser evaluation and preservation path.
Exactly four assigned Runs completed, two per condition, with no replacements.
Three products passed all 29 public requirements; one failed two requirements.
Product failure does not prevent this technical connection conclusion.

This is a technical pilot, separate from the historical 24 artifacts and any
confirmatory experiment. These four Runs do not establish compact efficacy,
quality preservation or noninferiority. Human review was **not run**.

## Fixed execution and the sole input difference

The [original plan](../research/protocols/ms1-catalog-technical-pilot-20260920.json)
was saved at 13:44:03 JST before live dispatch. Seed `3720733146551948321`
randomized the order of the two opposite-order pairs to compact → expanded,
then expanded → compact. The four slots below are the complete assigned cohort.
Each used a fresh Run instance, native session, workspace and state directory.

The installed [connection](ms1-catalog-technical-pilot.md) follows the
[adopted byte contract](ms1-catalog-return-two-condition-spec.md). Both profiles
use OpenCode 1.17.11, `deepseek-v4.1-flash`, the existing provider and credential,
a 1,800-second Run budget, a 600-second provider deadline and concurrency one.
There was no model switch, fallback, credential replacement or purchase.
The new runtime namespace is `MS1-001-catalog-v1`; historical locks are unchanged.

The controller and images were fixed at implementation commit
`58b263cd986fdf6aada1f52f7c7cb69e9820da6e`, based on PR #12's merge
`8c1d10b9187f7a8af84c3393854aff24688581ce`. The plan records the worker,
gateway and evaluator image digests. The evaluator DLL hash was
`594d79ddd2929eaabf0978f8f22bc8bcfcbcf4f06974b98f194b16961c063128` for
all adopted evaluations. No evaluator code was changed for this pilot.

Two model-free probes used the production profile constructor, worker,
OpenCode serializer and gateway with a container-local mock provider, synthetic
credential and no external provider route. After removing only the expanded
source packet, the complete captured first request bodies matched. The mock
then requested the same source range through the ordinary bash tool; the
actual result was present in each second request. Both probes passed and are
excluded from the four live Runs and their usage totals.

| Input check | Observed result |
|---|---|
| Common confirmation | Identical `common.json`: 982 UTF-8 bytes, contract hash matched |
| Derived catalog | Identical 58,349 bytes; 10 genres, 149 artists, 246 albums; contract hash matched |
| Source packet | 51,393 bytes including header; expanded suffix 52,375 bytes including common JSON |
| Full initial user prompt | Compact 7,522 bytes; expanded 58,915 bytes |
| Injection | Same initial user message, after common JSON, once in expanded and absent in compact; no serializer truncation |
| Other semantic input | Migration request, public requirements, system instructions and tool definitions matched |
| Actual worker access | Same paths, bytes, permissions and successful reads; write-open denied under the worker user |
| Range 1 / 80 | Same 4,293 bytes; SHA-256 `385b72c52f65cf61b7f825599e54a72e205299a2e9c8b93ea51f47d41337963c` |
| Range 361 / 71 | Same 15,566 bytes; SHA-256 `417690497f38620dc4d2172a15ffeee1c4ee82ec644ec5625b6a100ad9d4f04a` |

Worker checks covered the original Completed `SampleData.cs`, every generated
derived file and `/inputs/catalog-tools/catalog_return_contract.py`. The paths
in `common.json` were read inside the actual agent container, before OpenCode
started in that container. The whole legacy snapshot remained available under
`/inputs/legacy-source`. Harness preflight reads are recorded separately and
are not counted as model retrievals.

Every live first request was byte-identical to its corresponding mock request,
including both replicates. Request-body SHA-256 values were:

| Condition | Initial prompt SHA-256 | Serialized request SHA-256 |
|---|---|---|
| Compact | `af4b879a9856cb120d9473dfe564566d255c3d3ae4b6bdc94cbfc5664b838aa4` | `c6d8ed240fcfd53e7e44e1addac4cda35f0fa45b132b017c1b061e297ec400d4` |
| Expanded | `267976ce58e3ebbb8c6097a143cfcac03ea25acf47273cdadd1571082cea9e91` | `5fd4110515b1685a6fe7a10d86a9eb36f829c92367bc01ef8d5fc4de0681165c` |

Run IDs and timestamps remain in the execution records. They are not treatment
differences. Source manifests, prompt files, gateway receipts, raw requests and
provider/native tool-call identities provide the provenance chain.

## All assigned Run results

Run names below omit only the common `MS1-001-catalog-` prefix. All four ended
`completed`, exit code 0, with no budget timeout. Primary usage is provider
input plus output tokens over **every call**, including the failed product.

| Slot / pair position | Run | Calls | Input tokens | Output tokens | Total tokens | Runtime seconds | Final quality |
|---|---|---:|---:|---:|---:|---:|---|
| 1 / 1.1 | compact-001 | 38 | 2,113,778 | 39,677 | 2,153,455 | 525.071 | Fail, 27/29, 93.1 |
| 2 / 1.2 | expanded-001 | 43 | 2,739,200 | 43,709 | 2,782,909 | 305.956 | Pass, 29/29, 100 |
| 3 / 2.1 | expanded-002 | 50 | 3,066,698 | 42,653 | 3,109,351 | 665.185 | Pass, 29/29, 100 |
| 4 / 2.2 | compact-002 | 87 | 4,635,510 | 42,679 | 4,678,189 | 1,484.920 | Pass, 29/29, 100 |
| **All assigned** | **4 Runs** | **218** | **12,555,186** | **168,718** | **12,723,904** | — | **3/4 pass** |

Runtime is the existing harness interval from runtime startup through agent
completion and owned-process stop, including gateway startup and worker
preflight. It excludes later network cleanup, evaluation and archival.
Preparation has separate duration/exit records. These are descriptive timings,
not estimates of an intervention effect.

Passes/assigned Runs and passes/artifacts are both 3/4 overall, 2/2 expanded
and 1/2 compact. There are no artifact-free slots, supplements or excluded
failed Runs. All 218 raw request/response hashes, terminal usage records and
normalized totals were reconciled. Known input/output sums equal the complete
totals in every row; final primary-token missingness is zero. The two synthetic
probes and model-free evaluation recovery are not provider usage.

Provider usage shape changed during compact-002: calls 1–13 had the previous
top-level cache hit/miss fields; calls 14–87 instead exposed
`prompt_tokens_details.cached_tokens` and a null `cache_write_tokens` field.
Across the pilot there were 144 calls of the first shape and 74 of the second.
Primary `prompt_tokens` and `completion_tokens` remained present on every call,
and every response reported the fixed model ID. Optional cache-write usage is
unavailable, not zero. No provider-internal cause or routing change is inferred.

## Requirement coverage and the retained evaluation fault

The ordinary PR #12 evaluation covered all 29 public requirements, with
`agent_observed_C-015_C-016` in every final evaluation. Those two cases use
browser actions/observations plus saved HTTP checks; the other checks retain
their ordinary evaluator coverage. This is not a claim of browser testing of
every requirement or human acceptance. Final unchecked scope, evaluator faults
and unknown/blocked requirement counts are zero.

| Requirement | compact-001 | expanded-001 | expanded-002 | compact-002 |
|---|---|---|---|---|
| R-001 | Pass | Pass | Pass | Pass |
| R-002 | Pass | Pass | Pass | Pass |
| R-003 | Pass | Pass | Pass | Pass |
| R-004 | Pass | Pass | Pass | Pass |
| R-005 | Pass | Pass | Pass | Pass |
| R-006 | Pass | Pass | Pass | Pass |
| R-007 | Pass | Pass | Pass | Pass |
| R-008 | Pass | Pass | Pass | Pass |
| R-009 | Pass | Pass | Pass | Pass |
| R-010 | Pass | Pass | Pass | Pass |
| R-011 | Pass | Pass | Pass | Pass |
| R-012 | Pass | Pass | Pass | Pass |
| R-013 | Pass | Pass | Pass | Pass |
| R-014 | **Fail (C-015)** | Pass | Pass | Pass |
| R-015 | **Fail (C-016)** | Pass | Pass | Pass |
| R-016 | Pass | Pass | Pass | Pass |
| R-017 | Pass | Pass | Pass | Pass |
| R-018 | Pass | Pass | Pass | Pass |
| R-019 | Pass | Pass | Pass | Pass |
| R-020 | Pass | Pass | Pass | Pass |
| R-021 | Pass | Pass | Pass | Pass |
| R-022 | Pass | Pass | Pass | Pass |
| R-023 | Pass | Pass | Pass | Pass |
| R-024 | Pass | Pass | Pass | Pass |
| R-025 | Pass | Pass | Pass | Pass |
| R-026 | Pass | Pass | Pass | Pass |
| R-027 | Pass | Pass | Pass | Pass |
| R-028 | Pass | Pass | Pass | Pass |
| R-029 | Pass | Pass | Pass | Pass |

R-014 checks deletion from quantity two to one; R-015 checks deletion of the
last unit. Both were observed failures in compact-001. The product was retained.

Compact-001's **first evaluation failed technically**: the batch launcher's
sanitized child environment omitted `NODE_PATH` and
`SAMPLE2_BROWSER_EXECUTABLE`, so the browser collector could not resolve
installed Playwright. Further model dispatch stopped after that first Run.
A model-free launch/close probe verified the existing Node v24.15.0,
Playwright 1.62.1 and Chromium 149.0.7827.55. Supplying those two paths to the
ordinary `rescore` command evaluated the same frozen artifact successfully.
Its condition, prompt, input manifest, context, snapshot and usage hashes
remained unchanged. Evaluation sequence 1 remains an unadopted evaluator fault;
sequence 2 is the adopted 27/29 product failure. No model was rerun.

An append-only environment amendment was saved at 13:55:58 JST before the
remaining three slots. It pins the existing browser/dependency bytes and limits
recovery to those unstarted slots. Every adopted evaluation has the same
browser conditions and collector hashes. The original failed-evaluation archive
remains preserved; the recovered archive is a separate revision referencing it.
The original plan, dispatch journal and stopped-batch result were not rewritten.

After all four acquisitions, the launcher was fixed to pin and validate the
researcher browser dependencies before dispatch and forward the two paths to
the CLI. The exact acquisition source was retained before that change. This
subsequent launch fix was checked without another model Run; it is not presented
as code used by the original acquisition. It does not change evaluator logic.

## Retrieval and retained context

Counts below are completed native tool invocations reviewed against their
recorded commands and returned outputs. A joint query counts once in each file
category it reads. Programmatic copies/transformations are distinct from content
returned to the model. Listings, confirmation-only reads and harness preflight
are excluded. These are not counts of filesystem system calls. Full action IDs,
commands, raw-request references and output hashes are saved in the observation
and per-Run behavior records linked below.

| Run | Original catalog source reads | Raw packet file reads | Derived catalog content/query returns | Full catalog copy/transform | Range helper calls |
|---|---:|---:|---:|---:|---:|
| compact-001 | 1 | 0 | 3 | 1 copy | 0 |
| expanded-001 | 0 | 0 | 4 | 1 transform to C# | 0 |
| expanded-002 | 1 | 0 | 4 | 1 copy | 0 |
| compact-002 | 0 | 1 | 3 | 1 copy | 0 |

Compact-001 reread source lines 1–360 through the ordinary read tool; its cap
notice is retained. The actual returned tool message was 53,062 bytes, including
the tool's formatting. Compact-002 read the first 2,000 bytes of `raw-first.txt`
together with the first 3,000 bytes of the derived catalog. Both compact Runs
thus acquired information omitted from their initial message. This was permitted
behavior, with neither exclusion nor correction. Expanded-002 read the whole
source programmatically but returned only selected names/counts and mapping
checks in a 255-byte combined source/catalog response, not the whole source text.

Exact tool-message hashes were compared in all later serialized requests:

| Run | Output/context | Requests containing it | Exact later retentions |
|---|---|---:|---:|
| compact-001 | 53,062-byte source tool output | 33 | 32 after its first return |
| expanded-001 | Initial 51,393-byte raw packet | 43/43 | 42 after the initial request |
| expanded-002 | Initial 51,393-byte raw packet | 50/50 | 49 after the initial request |
| expanded-002 | 11,477-byte non-catalog legacy model-file output | 47 | 46 after its first return |
| compact-002 | 5,022-byte joint packet/catalog output | 80 | 79 after its first return |
| compact-002 | 13,418-byte directory listing | 85 | 84 after its first return |

For the descriptive large-tool-output inventory, the threshold was 10,000
returned UTF-8 bytes. Expanded-001 had no such tool output. The compact-002
packet/catalog row is included despite falling below that threshold because it
answers the omitted-information question. Byte retention does not itself
measure token cost or prove a causal effect; the primary usage table reports
actual provider totals.

## Recovery, preservation and validation

All four generation workers and gateways were confirmed stopped, with fresh
ownership checks, and their private networks were absent. The existing runtime
policy intentionally retains those **eight stopped containers** for evidence.
The two synthetic probes likewise retain four stopped containers. Runtime
images remain available. All owned browser-evaluation containers/networks were
removed and their cleanup receipts confirmed absence. There is no final
`cleanup_failed` result and no active process among these owned containers.

A final read-only diagnostic initially expected generation containers to be
absent. That assertion used the wrong lifecycle expectation; it was corrected
to the documented stopped-container retention policy. The failed check is
retained in `validation/final-check-correction.json`. It caused no model,
evaluator or cleanup rerun and is not recorded as a first-attempt pass.

| Validation | Result / boundary |
|---|---|
| Outer harness tests | 154 passed before acquisition; covers the installed connection |
| Research tests | 44 passed after the browser-launch fix |
| Model-free serializer/worker probes | Both conditions passed; synthetic usage excluded |
| Live slots | 4/4 completed; 3 products pass and 1 product fails |
| Evaluation attempts | 1 retained environment fault, recovered on the same artifact; 4 complete adopted evaluations |
| Raw usage and provenance | 218/218 calls reconciled; no final audit issue or primary-token missingness |
| Frozen conditions and archive integrity | Verified for all four; compact-001 also preserves the original archive and recovery revision |
| Human review | Not run |

The first fault and intermediate observations are retained separately from the
final results. No historical artifact was reevaluated, no old ZIP was rebuilt,
no exploration was rerun, and no historical token corpus was audited.

## Evidence references

Local originals are intentionally outside Git under
`runs/catalog-technical-pilot-20260920` and
`artifacts/catalog-pilot/20260920`. Repository publication of this report does
not publish those raw originals. The following links work in the originating
checkout; hashes allow the retained records to be checked independently.

| Record | SHA-256 |
|---|---|
| [Original plan](../research/protocols/ms1-catalog-technical-pilot-20260920.json) | `04c8cec02766cd73d504ea05fa0626b57ce03d0878f714818f544ecca414fc22` |
| [No-model connection result](../artifacts/catalog-pilot/20260920/connection-01/connection-result.json) | `65f556859ba202faccd67b0f5f6c2cd54002de8940dded6fd214ac8a3394dd7f` |
| [Contract byte check](../artifacts/catalog-pilot/20260920/connection-01/spec-byte-check.json) | `d167fc2dd0972a0e52955083cc246429727522ef46b672496d08b6e1c622c24b` |
| [Evaluation environment amendment](../artifacts/catalog-pilot/20260920/evaluation-environment-amendment.json) | `74994bf6df53331395e3e4761ce0916da622bf51c33d2cbe5b794a5c9d197deb` |
| [Final all-call observations](../artifacts/catalog-pilot/20260920/observations-final.json) | `eaf39aabc295c5fe45c8ef8591b33e63b3d09d7c41efe8c45e8ab117e5ddbb4c` |
| [Completion and per-Run ledger](../artifacts/catalog-pilot/20260920/completion.json) | `679bcaf13c9e4baf4d740cf6a29a66b431ea60d4700ece3caa91c784960e20fc` |

The completion ledger includes every requirement result, evaluation attempt,
archive identity/hash, browser cleanup receipt, native session and usage-format
inventory. [Acquisition-source manifest](../artifacts/catalog-pilot/20260920/acquisition-source/manifest.json)
identifies the exact pre-fix source. Behavior reviews are
[compact-001](../artifacts/catalog-pilot/20260920/behavior-compact-001.json),
[expanded-001](../artifacts/catalog-pilot/20260920/behavior-expanded-001.json),
[expanded-002](../artifacts/catalog-pilot/20260920/behavior-expanded-002.json) and
[compact-002](../artifacts/catalog-pilot/20260920/behavior-compact-002.json).
The read-only observation entry point is
[catalog_observations.py](../research/catalog_observations.py).

The technical gate supports moving to **separate confirmatory-plan fixation**.
That next plan must set repetitions, the primary comparison, quality criteria
and stopping rules before any further acquisition. No further model Run is
authorized or started by this report.
