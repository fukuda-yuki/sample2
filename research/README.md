# MS1 exploratory analysis

This directory contains research code, not an alternative agent/evaluator.
Start with the [Japanese findings](../docs/ms1-exploration-20260919-report.md),
[frozen protocol](../docs/ms1-exploration-20260919-protocol.md), and
[post-freeze change log](post-freeze-changes.md).

The historical population is the six direct children of
`runs/acceptance-64ad09cd85ca`. The new batch is
`runs/exploration-20260919-ms1`: two completed implementations, one environment
failure before model dispatch, fifteen undispatched slots, no supplements.
Its closed batch must not be silently resumed or combined with a later batch.

## Programs

- `analyze`: read saved provider requests/SSE and native trace; emit call,
  action, source-range and Run tables plus hash/audit receipts. No model or
  evaluator execution. Source files are read only, output directories are new.
- `summarize`: separate cohorts, distributions, complete-block contrasts,
  representative selection and scientific figures. Multi-label action counts
  overlap; output character exposure is not causal token attribution.
- `ledger`: all eighteen scheduled slots and any actually dispatched
  supplements, including missing/unstarted states and preservation receipts.
- `validate`: independently parse provider usage and recheck source hashes.
- `notebook`: produce an executed ipynb and readable standalone HTML companion.
- `review.ps1`: run only the prepared review copies, with separate human and
  automation state. This is not a model Run, and does not edit fixed artifacts.
- `freeze` / `acquire`: the already-used, bounded acquisition path. The exact
  pre-acquisition source is commit `5fa4977`. The frozen plan records its hashes.

The reporting files under `artifacts/exploration/20260919` and original Runs are
local research data and are deliberately not committed to Git. The report links
to them, and their SHA-256 receipts are preserved. Full call/action tables may
contain task code and tool commands; do not publish them indiscriminately.

## Environment and offline checks

Core extraction, ledger and validation use the standard library. Figures and
notebooks use a separate Python 3.14 virtual environment, with the recorded
packages in `requirements-analysis.txt`. It does not change the worker image.

```powershell
python -m unittest discover -s research/tests -v
python -m venv artifacts/exploration/analysis-env
.\artifacts\exploration\analysis-env\Scripts\python.exe -m pip install -r research/requirements-analysis.txt
```

The existing environment is already prepared; do not recreate it to read the
deliverable. Reproduction commands are in the report. Original and corrected
v1.0.1 outputs remain separate; the correction preserves unobserved totals as
null and leaves all measured values and classification rules unchanged.
