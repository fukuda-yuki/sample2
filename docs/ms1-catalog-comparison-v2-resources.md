# Catalog v2: information and resource comparison

**No candidate is currently adopted.** Recommend a fixed paired estimation
design after documenting usable model capacity, hours and storage reserve.
Current usage percentages are available; a defensible Run capacity is not.
The [machine comparison](../research/design-results/catalog-comparison-v2.json)
uses the existing v1 calculations and small algebraic additions. There are
zero new simulations or model Runs in this comparison.

## Information under explicitly assumed populations

| Pairs / Runs per condition | All Runs | Token reduction support probability | Mean token interval half-width | Mean quality interval half-width | Quality superiority probability, 85% vs 80% |
|---:|---:|---:|---:|---:|---:|
| 40 | 80 | 21.13% | 1,015,553 tokens | 27.18 pp | 0.425% |
| 80 | 160 | 38.46% | 723,687 tokens | 19.17 pp | 1.044% |
| 160 | 320 | 64.77% | 513,643 tokens | 13.46 pp | 2.785% |
| 320 | 640 | 90.66% | 364,325 tokens | 9.44 pp | 8.478% |
| 640 | 1,280 | 99.455% | 258,094 tokens | 6.63 pp | 25.754% |

Token columns reuse the saved lognormal scenario: true 20% reduction,
expanded mean reference 3,000,000, CV 1, pair correlation 0.25. Quality
half-width assumes both pass probabilities 0.8 and binary correlation 0;
superiority probability instead assumes 0.85 vs 0.8 with correlation 0.
The latter is from the saved exact calculation. The token and precision
scenarios have 20,000 historical replicates; Monte Carlo uncertainty remains
in the linked JSON. No parameter here is established by four pilot Runs.

**90.66% (rounded to 90.7% in v1) concerns token reduction only.** At 320
pairs under the 85%-vs-80% quality scenario, any joint-support probability is
at most 8.47769%, irrespective of the endpoints' dependence. The joint event
is a subset of quality superiority. Do not multiply the two probabilities.
Under equal true quality, requiring superiority does not become a well-powered
quality-maintenance test as N grows.

These widths are scenario means, not guaranteed realized precision. All
concordant outcomes at 320 pairs give approximately +/-1.36005 pp instead;
both all-pass and all-fail data have that relative interval. Neither equality
nor an interval containing zero proves maintenance or practical adequacy.

| Candidate | Potentially useful information under these scenarios | Important unresolved conclusions |
|---|---|---|
| 40 | Coarse effect estimates, conspicuous failures, retrieval/retention and call behavior | Low reference power and roughly +/-27 pp quality precision cannot settle small quality changes or typical 20% token effects reliably |
| 80 | Improved coarse estimates and more behavior observations | Reference token detection remains below 40%; quality remains broad |
| 160 | More informative mean contrasts; quality resolution around +/-13.5 pp | Missed 20% reductions remain plausible; a 5 pp quality advantage rarely supports superiority |
| 320 | Stronger reference token sensitivity, quality resolution near +/-9.4 pp | No well-powered joint superiority claim; no maintenance claim; substantial resource and missingness burden |
| 640 | Higher token sensitivity and narrower quality differences | Even 5 pp quality superiority has only about 25.8% support probability; no justified maintenance bound; storage reference exceeds current free space |

All candidates can yield useful estimates or failures with stated uncertainty;
none guarantees the scientific relationship will be resolved. Resource-based
selection must explain why that uncertainty is useful for the next research
decision. It is not an instruction to spend the entire available allowance.
See [Lakens on resource-constrained sample-size justification](https://lakens.github.io/statistical_inferences/08-samplesizejustification.html).

## Residual missingness sensitivity

For a hypothetical independent probability q of a **truly unknown endpoint
value per Run after recovery**, availability of all values is `(1-q)^(2*n)`:

| Pairs | All Runs | q = 0.1% | q = 0.5% |
|---:|---:|---:|---:|
| 40 | 80 | 92.31% | 66.97% |
| 80 | 160 | 85.21% | 44.84% |
| 160 | 320 | 72.60% | 20.11% |
| 320 | 640 | 52.71% | 4.04% |
| 640 | 1,280 | 27.79% | 0.164% |

These are **assumptions, not measured failure rates**, and the table applies
separately to the endpoint's own missingness probability. Correlated outages
can behave differently. Do not multiply these probabilities by power without
a model for the relationship between missingness and outcomes.

For tokens, true missing usage still prevents the all-assigned primary
interval. For quality, one valid confirmed requirement failure fixes the
binary result at 0: incomplete inspection elsewhere is not a missing binary
value and need not lower binary availability. For truly unknown binary
results retain bounds/envelopes and withhold superiority; complete tokens
remain independently analyzable. No endpoint is redefined using only the
convenient complete or successful cases.

## Read-only resource evidence, 2026-09-21

The [local inventory](../research/design-results/catalog-resource-snapshot-20260921.json)
was measured at 13:38 JST. It enumerated existing files and saved timestamps;
it did not execute an evaluator, model or archive builder.

| Resource | Observed / confirmed | What remains unknown |
|---|---|---|
| Host disk | C: free **290.40 GiB**; `runs/` 41,478,549,163 logical bytes; `artifacts/` 82,701,017,233 logical bytes | Space reserved for other work, future Docker growth, backup overhead and the task's acceptable reserve |
| Pilot retention | Full four-Run cohort **1.728 GiB**, including saved archives and recovery material; no enumeration errors | Future tail of request/trace/artifact sizes; it is not a worst-case storage bound |
| Pilot runtime | 305.956–1,484.920 seconds per Run, mean 745.283 | Future mean/tails and hours actually available; the 1,800-second runtime budget excludes other phases |
| Adopted evaluation spans | Four saved spans: 39.923, 28.945, 21.990 and 26.406 seconds; mean 29.316 | Preparation before the first saved evaluator timestamp, later archival and future recovery costs |
| Failed evaluation span | One retained environment-fault attempt: 15.444 seconds, separate from adopted attempts | Frequency of future faults; this one observation does not estimate a failure rate |
| Subscription/model/key | OpenCode Go and DeepSeek V4.1 Flash confirmed by user; user-environment key present | No missing key or request for a new credential |
| Current account usage | GET usage returned HTTP 200 at **13:42 JST**: rolling 0%, weekly 0%, monthly 14% used | Actual DeepSeek Run capacity; cache mix, peak/off-peak timing, other usage and future limit changes |

The scoring span is from the earliest saved HTTP/composed evaluator
`startedAt` through that attempt's `evaluations/index.jsonl recorded_at`.
It includes the observed browser/cleanup interval, excludes waiting between
recovery attempts, and is **not** an end-to-end evaluation benchmark. Each
timestamp source/hash is retained in the inventory. No historical products
were rejudged.

The account readback reports reset times of 2026-09-21 18:42 JST (rolling),
2026-09-28 09:00 JST (weekly) and 2026-10-09 12:46 JST (monthly). Reported
remaining fractions are 100%, 100% and 86%, subject to the API's precision and
subsequent usage. These are account-window fields, not a model-specific token
balance. The sanitized receipt is local at
`artifacts/catalog-comparison-v2/opencode-go-usage-20260921.json`, with a copy
of its allowed usage fields and its hash in the machine comparison. It contains
no key or account ID. The [official GET route source](https://github.com/anomalyco/opencode/blob/dev/packages/console/app/src/routes/zen/go/v1/usage.ts)
was checked before using the existing key. No generation request was made.

Public [Go documentation](https://opencode.ai/docs/go/) checked on 2026-09-21
lists DeepSeek V4.1 Flash off-peak input/output/cache-read rates of
$0.15/$0.60/$0.003 per million tokens, and peak rates of
$0.30/$1.20/$0.006. The displayed $60 monthly allowance is promotional
(normally $15), ending September 27; rolling and weekly limits are documented
as 20% and 50% of the monthly allowance. These public terms do not prove the
user's remaining model-specific capacity over a future study calendar. No
contract change, purchase, paid overage or fallback was enabled or assumed.

## Scaling the existing pilot, not claiming feasible capacity

| Pairs | Total tokens reference | Runtime hours reference | Adopted scoring-span hours reference | Retained GiB reference | Quota-dollar scenario range |
|---:|---:|---:|---:|---:|---:|
| 40 | 254,478,080 | 16.56 | 0.65 | 34.56 | 2.78–79.38 |
| 80 | 508,956,160 | 33.12 | 1.30 | 69.12 | 5.56–158.76 |
| 160 | 1,017,912,320 | 66.25 | 2.61 | 138.24 | 11.11–317.52 |
| 320 | 2,035,824,640 | 132.49 | 5.21 | 276.48 | 22.22–635.04 |
| 640 | 4,071,649,280 | 264.99 | 10.42 | 552.95 | 44.45–1,270.09 |

Token/runtime columns reproduce v1 scaling of the four pilot Runs. Storage
scales the **whole retained cohort**, not just its smallest product directory.
Scoring spans scale only adopted evaluations; the retained fault is separately
reported and is not silently averaged away or treated as a new sample.
Runtime + scoring is still not full wall time. Preparation, archival, pauses
and recovery add time. A nominal 640-Run runtime-budget sum alone is 320 hours.

Quota-dollar ranges apply the documented rates to the saved four-Run
12,555,186 input and 168,718 output tokens, then scale by total Runs / 4.
The low end assumes **all inputs are cached at off-peak rates**; the high end
assumes **no cache hits at peak rates**. They are deliberately broad scenarios,
not observed costs, invoices, spending caps or Run-capacity bounds. Real Run
lengths are not bounded by the pilot, and even this broad cost range shows why
total tokens or the reported 86% monthly remainder cannot determine N alone.
The primary scientific token metric remains unweighted input plus output.

At 320 pairs, the retention reference leaves only about **13.92 GiB** of the
current free space before other growth. At 640 pairs, it exceeds current free
space. Smaller candidates reduce the burden but their actual feasibility
still depends on hours, model allowance and a chosen reserve. No candidate
passes a verified-capacity gate today. This supports deferring numerical
allocation while adopting the revised metric-specific design.

Reproduce the comparison from saved inputs with the existing analysis Python:

```powershell
artifacts/catalog-confirmatory-design/analysis-env/Scripts/python.exe -m research.catalog_resources compare --resources research/design-results/catalog-resource-snapshot-20260921.json --usage artifacts/catalog-comparison-v2/opencode-go-usage-20260921.json --out <new-comparison.json>
```

Only a new resource inventory changes the snapshot time/measurements. Reusing
the snapshot performs algebra and table selection, not a new simulation. Do
not clean up original data to make a candidate appear feasible.
