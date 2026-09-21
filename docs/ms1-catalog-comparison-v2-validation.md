# Catalog comparison v2: validation and scope

**Ready within the reviewed offline scope.** The revision repairs the two
reported analyzer defects, implements separate endpoint inference, and supplies
one resource-bounded design with numerical allocation explicitly deferred.
This is not acceptance of a new acquisition campaign or confirmation result.

## Executed validation

| Check | Result | Evidence / limit |
|---|---|---|
| Full `research/tests` suite on final analysis source | **91 passed, 0 failed** | Existing Python 3.14.4 / NumPy 2.5.3 / SciPy 1.18.0 environment; includes 47 analyzer/resource tests and 44 existing research tests |
| Original PR #14 defect reproduction | **Both reproduced** | Loaded exact Git blob `47a5e8edb5ffa63ef63270ec058af95488caf256` from `dfcf35de...`; synthetic data only |
| Shared receipt validation | **Pass** | Forged/missing records, required fields, incomplete/changed code hashes, plan hashes, direct file/object mismatch and conflicting input paths |
| Ordinary analyzer CLI | **Pass** | Valid explicit and embedded receipts succeed; invalid explicit/embedded receipts fail before an output file is created |
| Support-flag gating | **Pass** | Wrong model suppresses target, token, quality and conjunction flags; pilot output cannot claim confirmation |
| Endpoint separation | **Pass** | Valid known failure + incomplete inspection remains binary 0; unknown quality does not veto complete tokens; missing usage does not veto valid quality superiority; identity mismatch remains blocked |
| Operational separation | **Pass** | Cleanup and missing behavior observations stay visible without automatically vetoing valid primary measurements |
| Interval checks | **Pass** | Paired t against independent SciPy paired-test API; exact binomial intervals against binomtest; nondegenerate all-concordant quality interval; conservative unknown-outcome envelopes |
| Resource/missingness comparison | **Pass** | Reuses saved v1 values; independent algebra checks 640-Run token scaling and endpoint availability; no new large simulations |
| Local resources and provider usage | **Read-only evidence obtained** | File inventory/saved timestamps and authenticated GET usage API; no generation or billing-setting request |
| Historical v1 preservation | **Pass** | Historical documents, plan, calculation, freeze and pilot smoke output match their original Git bytes |

The previous complete suite had 73 tests; this revision adds 18 tests
(16 in the analyzer suite and 2 resource tests) and revises old expectations
to match the v2 metric-specific contract. Test counts are not model Run counts.
The saved final log is
`artifacts/catalog-comparison-v2/research-tests-reviewed.log`; the earlier
42-test and 89-test checkpoints are not added to the final total. The
89-test log is retained separately as `research-tests-final.log`.

The [machine validation receipt](../research/design-results/catalog-comparison-v2-validation.json)
contains the executed check results, relevant source hashes and preservation
checks. The [revision freeze](../research/design-results/catalog-comparison-v2-freeze.json)
binds the deliverable files. Neither is a pre-dispatch launch receipt.

## Reproduction of the two reported defects

The original file SHA-256 is
`23c8ebafb3b90ab493e0bf664e78f4a9a3da520c4522dd8edd3ddd1879827a2b`,
matching the v1 freeze. The original bytes are saved locally at
`artifacts/catalog-comparison-v2/pr14-catalog_confirmatory.py`.

Forty synthetic pairs have lower varying compact token totals, compact
passes and expanded failures. Only inside this synthetic fixture, the planning
target is 100 tokens so the auxiliary flag is decisively true before corrupting
identity. The real v2 planning scenario remains 600,000 tokens.

| Synthetic case | Original PR #14 analyzer | Revised analyzer |
|---|---|---|
| Embedded `launch_receipt: {test: true}` | `token_reduction_and_relative_quality_supported` | ValueError: incomplete pre-dispatch receipt |
| Wrong model on otherwise favorable data | `decision: indeterminate`, target-reduction flag **true** | `decision: indeterminate`, all relevant support flags **false** |

The local result is
`artifacts/catalog-comparison-v2/regression-reproduction.json`, summarized
in the machine receipt. The user-provided sandbox ZIP was not used; these
cases were rebuilt from the described inputs and the exact original Git blob.
No claim is made that every test or file in that external ZIP was reproduced.

The final suite additionally verifies quality superiority independently of
missing token usage, partial-coverage failure under a wrong evaluator, unknown
provenance faults, zero-variance token data, all-fail populations, no-dispatch
zero handling, fixed denominators, duplicate identities, and output
non-overwriting. The analysis itself is checked with network/subprocess calls
disabled; separate CLI tests invoke only the offline analyzer.

## Work deliberately not performed

| Work | State |
|---|---|
| New experimental model Runs / re-pilot | **Not run (0)** |
| Re-evaluation of the existing 24 products | **Not run (0)** |
| Live evaluator/browser execution | **Not run (0)** |
| ZIP creation/recreation | **Not run (0)** |
| Re-audit of all 218 raw pilot calls | **Not run**; saved summaries/timestamps read for resource references |
| Full v1 Monte Carlo regeneration with identical random stream | **Not run**; frozen results reused, no new simulation infrastructure |
| Evaluator, browser collector or model-runner changes | **None** |
| New human quality/UX review | **Not run** |
| New Run count / acquisition authorization | **Not adopted / not authorized** |
| Remote publication, new PR, CI or merge of this revision | **Not performed** |
| misc amendment | **Local proposal only** |

The source review and synthetic validation support the limited analyzer and
design changes. They do not replace ordinary live acquisition evidence. Prior
technical-pilot/evaluator acceptance is retained under the PMO instruction;
this work neither revokes it nor claims a new acceptance run.

The initial browser attempt reached a login page without changing settings.
The subsequent official GET usage route succeeded with the existing user key;
this supersedes the initial uncertainty about available account usage fields.
Key values and authentication headers were never printed or saved. No new
key, account, subscription, credit purchase or paid fallback was requested.
