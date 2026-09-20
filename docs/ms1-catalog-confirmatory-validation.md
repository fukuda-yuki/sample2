# Offline confirmation-design validation — 2026-09-20

**Ready within the reviewed planning/analysis scope. Acquisition not run.**
The [plan](ms1-catalog-confirmatory-plan.md) is an executable analysis and
an operational runbook for a later authorized acquisition, not a new launcher
or completed confirmation experiment. The technical pilot stays accepted.

## Verification ledger

| Check | Result | Evidence and scope |
|---|---|---|
| Requested implementation baseline | Pass | Current starting merge `b5083f0a296a8afb4d9161825f5bf9ceedab457e`; tree equal to reviewed `3c2f61926e8427eca3efcbdb4784f5373b5f9cf9` |
| Canonical research and quality-margin search | Pass | GitHub `misc` revision `797dde53f29dd3512d91699dc69b5cd8a8d607c9`, Protocol, Research Questions, Research Plan; also local input contract, overall plan and exploration proposal. No numeric allowable pass-rate loss/floor found in this reviewed scope |
| Allocation and frozen input identities | Pass | 320 pairs, 640 unique Run IDs, one of each arm per pair, reproducible independent order; pinned source/profile/classifier/collector files match accepted checkout |
| Parametric design calculations | Pass | Fixed-seed 20,000 replicates per cell; normal-power formulas, lognormal/contaminated tails, positive/zero/negative pairing, quality multinomial scenarios, resource scenarios |
| Statistical implementation cross-check | Pass | Paired t CI/p-value versus independent SciPy API; beta-quantile CP versus exact binomial inversion API; exact quality-rule power versus explicit small-n multinomial enumeration; all-concordant interval versus closed form |
| Research tests | Pass | 73 tests: 44 existing offline tests and 29 new analysis/design tests. No model, live browser or original-product evaluation required |
| Four-Run input/output smoke check | Pass | Reads existing `observations-final.json`; 4 Runs / 2 pairs / 218 saved call records; sum 12,723,904; compact mean 3,415,822, expanded mean 2,946,130; difference +469,692; ratio 1.1594267734; quality 1/2 versus 2/2. Output explicitly `not_a_confirmatory_result` |
| Frozen design reproduction | Pass | Recalculation and stored JSON compared with identical plan and seed; versioned Python/NumPy/SciPy. SHA-256 receipt accompanies delivery |
| New model Runs / repeat pilot | Not run | Explicitly outside this work |
| Re-evaluation of historical 24 / ZIP recreation | Not run | Original research artifacts untouched; ordinary unit tests use disposable synthetic fixtures |
| Docker, evaluator build, live browser checks | Not run | Accepted connection/evaluator evidence reused; this work changes neither |
| New 218-call original-data audit | Not run | Smoke validation checks the already-saved observation input; it is not a fresh raw request/SSE provenance audit |
| Human review / actual resource availability | Not run | No claim of human acceptance, available quota, money or capacity |
| misc update / remote publication | Not performed by this work | Canonical amendment is a local proposal |

## Regression meaning

The new synthetic tests cover lower tokens with failed quality; both arms
failing; all successes retaining nonzero uncertainty; missing usage and missing
scheduled Runs; known product failure alongside incomplete coverage; unknown
quality bounds; 218 calls remaining four Run samples; budget stops; affirmative
zero-dispatch evidence; duplicate/foreign cohorts; model and cleanup faults;
success-only selection; invalid adoption/artifact state; partial source reads;
and no network/subprocess activity in analysis. Output creation refuses
overwriting existing evidence. These are analysis validations, not new product
acceptance tests.

No inference about intervention efficacy comes from these controls or the
old pilot. The recommendation relies on declared design assumptions. At equal
quality there is no finite sample-size solution for high-power acceptance of
the strict zero-loss rule. This limitation is in both the plan and machine
output, not concealed behind a successful test count.

## Reproduction and receipts

Use `research/requirements-confirmatory.txt` in the dedicated local environment;
the analysis environment used Python 3.14.4, NumPy 2.5.3 and SciPy 1.18.0.
The main plan supplies no-model reproduction commands. Test logs and detailed
pilot-smoke output remain under `artifacts/catalog-confirmatory-design/`;
the committed [smoke summary](../research/design-results/catalog-pilot-smoke-summary.json)
contains aggregate values and source hashes, with no raw prompts or secrets.
The [freeze receipt](../research/design-results/catalog-confirmatory-v1-freeze.json)
binds the plan, code, calculations, documents and tests. It is a design receipt,
**not** the future pre-dispatch launch receipt or an execution authorization.

During development, earlier calculations and smoke checks were retained as
separate local files. The final committed calculation corresponds to the
negative-correlation sensitivity addition and exact quality-power computation;
earlier draft simulation values are not blended into it. Minor floating-point
rounding is bounded to valid probabilities. No scientific endpoint was changed
in response to new experimental observations because none were acquired.
