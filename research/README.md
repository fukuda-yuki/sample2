# MS1 exploratory analysis

This directory contains research code, not an alternative agent/evaluator.
The [first-pair sharing rehearsal](../docs/ms1-catalog-sharing-rehearsal.md)
now records actual Release upload, anonymous download, hash-verified restore and
identical offline extraction. Its tested pair-admission rule remains proposed;
the user confirmed paid overage is disabled, so monetary limits are not a start
condition. API unavailability causes a pause. Storage checks, execution freeze
and separate experiment start approval remain required.
The current deliverable is the [catalog comparison v2 revision](../docs/ms1-catalog-comparison-v2-plan.md):
metric-specific inference, resource/information comparisons and tested offline analysis.
The subsequent [allocation and data-sharing proposal](../docs/ms1-catalog-allocation-sharing.md)
records the user's full resource allocation, a justified 320-pair working candidate,
and the evidence needed for independent analysis from this GitHub repository.
No Run count is adopted and no model acquisition is authorized. The
[v1 confirmation design](../docs/ms1-catalog-confirmatory-plan.md), its 320-pair
candidate and saved calculations are historical, not the current execution plan.
The dedicated analysis dependencies are in
`requirements-confirmatory.txt`; the existing analysis environment is separate.
Start with the [uniform browser correction](../docs/ms1-browser-cart-20260919-report.md),
[correction and original-first audit](../docs/ms1-correction-20260919-report.md),
[historical Japanese findings](../docs/ms1-exploration-20260919-report.md),
[frozen protocol](../docs/ms1-exploration-20260919-protocol.md), and
[post-freeze change log](post-freeze-changes.md).

The historical population is the six direct children of
`runs/acceptance-64ad09cd85ca`. The new batch is
`runs/exploration-20260919-ms1`. The first segment stopped after two completed
implementations and one pre-model Docker failure. The user's explicit retry
instruction authorized a documented continuation; see the
[retry amendment](../docs/ms1-exploration-20260919-retry-amendment.md).
Its original plan, result, and failed attempt remain preserved. The appended
journal and `resume-v1/result.json` record continuation separately.
The continuation completed all eighteen original slots and one late supplement:
eighteen model executions plus the preserved pre-model failure. The final
analysis contains 955 new calls; the historical six retain exactly 322 calls.

## Programs

- `catalog_share`: stage the first pilot pair, scan public copies, bind a review
  to exact bytes, package, safely restore and extract saved SQLite/OTLP offline.
  Exclusions/licenses are explicit; it does not upload or dispatch anything.
- `catalog_admission`: check local storage, an outstanding API recovery pause,
  execution freeze and start authorization. Financial limits, dollar reservations
  and reset horizons are not gates under the user's no-overage policy. This is
  not yet integrated into an acquisition controller.
- `catalog_design`: reproduce parametric sample-size, precision and resource
  scenarios for historical v1 without models, Docker or evaluation. Its default
  remains v1; it does not choose the v2 allocation.
- `catalog_resources`: read file sizes/saved evaluation timestamps or reuse v1
  calculation rows with algebraic missingness and resource scenarios. No new
  simulations, model execution, evaluation or account mutation.
- `catalog_allocation_review`: inspect the four existing pilot SQLite databases
  read-only, reconcile their saved OTLP with normalized usage, and calculate
  cache-mix quota references. No provider re-audit, acquisition or publication.
  `sql/catalog_otel_requests.sql` exposes each saved request span, its identity,
  timing, reported usage and original JSON for independent SQL analysis.
- `catalog_confirmatory`: analyze plan-bound saved catalog observations at Run
  and pair level; retain missingness and product failure. `--purpose pilot_smoke`
  cannot set any confirmatory support flag. Confirmation requires a saved,
  allocated v2 plan and the same validated receipt through every input path;
  the current unallocated v2 plan intentionally cannot analyze confirmation data.

- `analyze`: read saved provider requests/SSE and native trace; emit call,
  action, source-range and Run tables plus hash/audit receipts. No model or
  evaluator execution. Source files are read only, output directories are new.
- `summarize`: separate cohorts, distributions, complete-block contrasts,
  representative selection and scientific figures. Multi-label action counts
  overlap; output character exposure is not causal token attribution.
- `ledger`: all eighteen scheduled slots and any actually dispatched
  supplements, including missing/unstarted states and preservation receipts.
- `validate`: require a plan-backed expected-Run inventory and corpus root;
  independently enumerate requests from original journals, reconcile IDs,
  reparse SSE usage, and verify normalized/analysis values and original hashes.
- `notebook`: produce an executed ipynb and readable standalone HTML companion.
- `prepare_reviews` / `review-resumed.ps1`: prepare and run the final selected copies, with separate human and
  automation state. This is not a model Run, and does not edit fixed artifacts.
- `review.ps1` is retained for the earlier stopped-segment materials only.
- `completion`: require the revised independent audit, expected inventory,
  original-file receipt, and acquisition-era code; reject unexpected audit
  issues and verify archived packages and frozen conditions. It is portable
  and does not require the original host's Docker containers.
- `correction_inventory`: bind planned and dispatched attempts to preserved
  packages without consulting analytical tables.
- `rejudge`: compare R-029 with the old/new evaluator DLLs and separately score
  changed artifacts using all original requirements and the original sandbox.
  Ordinary frozen `rescore` safeguards remain unchanged.
- `correction_report`: reproduce quality impact, representative selection and
  all-call provider usage format tables without model execution.
- `browser_rejudge`: apply the ordinary scorer's real-browser C-015/C-016 phase
  to the inventory of saved artifacts; retain the R-029 baseline and save new
  results. `--observations` reuses bound captures for a judgement-only correction.
- `verify_browser_path`: exercise `score_run` and `aggregate.row_for` on disposable
  copies of specified saved instances, with an explicit expected verdict. These
  are evaluation integration controls, never additional research/model Runs.
- `handoff`: build a full local bundle including raw data and evaluator image,
  then verify it under an explicitly relocated root. Never uploads artifacts.
- `report`: regenerate this batch's Japanese report and tables from final analysis.
- `evidence_review`: post-acquisition evidence index for every Run, linking large
  input increases, retained outputs, error-text review candidates and quality.
- `resume` / `network_recovery`: explicitly authorized continuation and narrowly
  scoped cleanup of preserved, stopped Run networks. No global Docker pruning.
- `freeze` / `acquire`: the already-used, bounded acquisition path. The exact
  pre-acquisition source is commit `5fa4977`. The frozen plan records its hashes.

The reporting files under `artifacts/exploration/20260919` and original Runs are
local research data and are deliberately not committed to Git. The report links
to them, and their SHA-256 receipts are preserved. Full call/action tables may
contain task code and tool commands; do not publish them indiscriminately.

## Environment and offline checks

Core extraction, ledger and validation use the standard library. The full
test suite additionally needs the confirmation design's NumPy/SciPy environment;
prepare it using the linked confirmation plan. Figures and
notebooks use a separate Python 3.14 virtual environment, with the recorded
packages in `requirements-analysis.txt`. It does not change the worker image.

```powershell
artifacts/catalog-confirmatory-design/analysis-env/Scripts/python.exe -m unittest discover -s research/tests -v
python -m venv artifacts/exploration/analysis-env
.\artifacts\exploration\analysis-env\Scripts\python.exe -m pip install -r research/requirements-analysis.txt
```

The existing environment is already prepared; do not recreate it to read the
deliverable. Reproduction commands are in the report. Original and corrected
v1.0.1 outputs remain separate; that correction preserves unobserved totals as
null. Post-acquisition v1.0.2 also accepts nullable SSE tool deltas, with a
recorded regression comparison of all prior rows. Measured values and frozen
classification rules are unchanged. The continuation's frozen source copies
remain available even though the current reader includes this correction.

The latest core controller was repaired after acquisition. Do not use current
controller hashes to judge whether the preserved acquisition code changed.
Follow the correction report or the bundle's `README-ja.md` for the new audit
commands; the original completion receipt is historical, not the current gate.
