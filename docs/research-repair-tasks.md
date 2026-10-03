# Migration task repair (Issue #22)

This repair supplies one executable source family, `music-store-continuity`, and two nested semantic variants, `MS1-CONT-A` and `MS1-CONT-B`. It supports apparatus validation and a conditional exploratory comparison on this family. It does not establish migration quality across independent applications. The independent-family and basic human-confirmation acceptance items remain incomplete.

The [candidate register](../research/tasks/candidate-register.json) fixes selection before model outcomes. Two independent workflow ideas remain unselected design candidates with no obtained source, executable reference or allocation contribution. Six tasks have not been adopted. Both A and B belong to calibration/exploratory development; the independent held-out family set and research held-out variant set are empty. A control withheld from evaluator development is an evaluator calibration control, not a held-out research application.

## Public contract and authority

Both profiles contain exactly the same bytes from [public-request.txt](../research/tasks/music-store-continuity/public-request.txt). The request exposes the migration boundaries and observation interface but no variant-specific amount, rate or answer. Source and raw existing business data have the same read access in both experimental arms. `explore` and `preload` may differ in initial presentation of those same assets; neither receives the private oracle or modern reference.

The source family is the public `chack411/MVC-Music-Store` `net48` branch at `2967afb9d69488641df0d154e2ad5827a7820e71`. Its tutorial and sample2 reference solutions are publicly known. Its readme declares code Ms-PL; no upstream LICENSE file was found in the retained source. This repair adds an explicitly researcher-authored current pricing policy and synthetic operational SQLite installation. They are not observations from a deployed customer system, and the variants are not independent repositories. Contamination has not been eliminated.

The pinned old source is read without mutation. Preparation copies it into a new local asset namespace, overlays `SourcePricingPolicy.cs`, updates the cart/order/current-price expressions and source project inclusion, and provides a lossless raw row export in `OperationalData/existing-data.json`. A full SQLite snapshot is separately supplied in `existing-business/initial-store.sqlite`. `preparation.json` records the original source file hashes and all derived file hashes. The old ASP.NET Framework/SQL Server application is **not_run**; a .NET 8 compatibility reference is actually executed instead. Compatibility authority is the public contract, explicit preserved raw snapshot, source pricing rule, manually derived arithmetic assertions and a separate Python Decimal calculation, rather than the modern reference alone. Human confirmation of that authority remains **not_run**.

The generated evaluator-only directory holds a variant-specific expected `catalog.json`, `migration-oracle.json` and an exact initial SQLite copy. These are excluded from implementation inputs. The oracle's `tables` entries give primary keys and every preserved column of every old row; `pricing` and `workflow` identify current policy and independently specified expected amounts. A and B agreed on evaluator version `1.3.0`, variant-specific requirement ledgers, critical `R-030/C-031`, and mandatory ordinary browser coverage. A owns those ledgers and the ordinary scorer integration; B owns assets, references, profiles, preparation and the independent checker.

## Necessary source/data information

| Observation | Variant A | Variant B |
| --- | --- | --- |
| Raw album 1 / 2 / 3 prices | 7.25 / 12.40 / 0.95 | 9.95 / 2.75 / 15.50 |
| Source policy | rate 1.00, each unit rounded to cents away from zero | rate 0.90, each unit rounded to cents away from zero |
| Current album 1 / 2 / 3 prices | 7.25 / 12.40 / 0.95 | 8.96 / 2.48 / 13.95 |
| Checkout: album 1 quantity 2, album 2 quantity 1 | 26.90 | 20.40 |
| Immutable historical order 7001 | 32.75 = 3×7.25 + 1×11.00 | 25.15 = 2×9.95 + 1×5.25 |

These manually specified assertions are stored separately in [variants.json](../research/tasks/music-store-continuity/variants.json) and independently recomputed with Python Decimal. B's 9.95×0.90=8.955 and 2.75×0.90=2.475 are rounded **per unit** to 8.96 and 2.48 before multiplying quantities. Merely satisfying a generic storefront description cannot fully pass the declared source-specific monetary and preserved-data requirements. A fixed implementation using A's effective values on B's data produces 26.90 when B requires 20.40, and fails current cart/order/restart amount checks. This establishes information dependence; it does not prove that any model read source.

## Preserved, corrected and excluded behaviour

Preserved observations cover all 246 album identifiers/titles/genre and artist relationships/raw catalog amounts, customer 301, historical order 7001, detail identifiers 9101/9102, historical detail quantities/unit prices, customer/order relationship and retained cart 5001 for album 41 quantity 3. Old row values are checked before startup, after ordinary operations, before/after process restart, and after new checkout. Current catalog values are not substituted for historical unit prices. New order/detail identifiers avoid collisions with existing identifiers, and persisted new order totals equal the sum of quantity times current effective unit price. Extra tables/columns and semantically equivalent money storage are permitted by the independent checker.

Declared corrections cover missing/foreign cart-line removal without cross-session mutation, complete address validation without changing cart/history, and the visible removal control updating the current page's row, amount and count. Administration, authentication/login, external integrations, concurrency/performance and maintenance-effort judgments are excluded. Preserving retained cart **database rows** is measured; durable server-side login/session state across host restart is not claimed. Other source-specific rules require a future declared task contract.

## Finite technical receipts and reproduction

The finite B case plan is one A compatibility reference, one B reference and one A-fixed-on-B negative control. Each executes the same HTTP/SQLite workflow, restart and fresh-path import. No model is dispatched. Four targeted unit controls cover public prompt equality/nesting, independently recomputed monetary assertions, historical corruption detection, and allowed schema/money alternatives. Ordinary scorer/browser/composition/cleanup calibration is a separate A-owned receipt on these same packages.

The final B receipt is `artifacts/task-acceptance-v2/workflow/summary.json`: A and B each pass 18 checks, while the A-fixed-on-B control fails the four intended current-amount observations (26.90 instead of 20.40). Fresh-path reference import passes for all three cases, and all four unit controls pass. These are technical compatibility/reference results with `human_review=not_run` and zero model dispatches.

An initial local sandbox startup failed because Windows EventLog writing was denied. Its raw logs are retained under `artifacts/task-acceptance-v1/workflow/`; it is an environment failure, not a product failure. The owned process was identified by its exact application path and stopped. A later normal-user workflow recorded A/B positive passes and the expected fixed-control failure. Ordinary collection then exposed a reference packaging defect: collected artifacts exclude `*.sqlite`, so an unconditional project Content include caused publish failure. Version 2 makes that include optional and reads the supplied input SQLite when needed; the failure and prior receipts remain preserved. Windows unit controls also exposed Python SQLite connection lifetime; connections now close explicitly.

From a clean integrated checkout, prepare input assets, then generate references in a **new** output directory:

```powershell
python -m research.migration_tasks prepare
python -m research.migration_tasks reference --variant A --out artifacts\task-acceptance-v2\reference-A
python -m research.migration_tasks reference --variant B --out artifacts\task-acceptance-v2\reference-B
python -m research.migration_tasks reference --variant B --fixed-variant A --out artifacts\task-acceptance-v2\fixed-A-on-B
dotnet publish artifacts\task-acceptance-v2\reference-A\MusicStore.Continuity\MusicStore.Continuity.csproj -c Release -o artifacts\task-acceptance-v2\published-A --nologo
dotnet publish artifacts\task-acceptance-v2\reference-B\MusicStore.Continuity\MusicStore.Continuity.csproj -c Release -o artifacts\task-acceptance-v2\published-B --nologo
dotnet publish artifacts\task-acceptance-v2\fixed-A-on-B\MusicStore.Continuity\MusicStore.Continuity.csproj -c Release -o artifacts\task-acceptance-v2\published-fixed --nologo
python -m research.verify_migration_tasks --published-root artifacts\task-acceptance-v2 --out artifacts\task-acceptance-v2\workflow
python -m unittest research.tests.test_migration_tasks -v
python -m research.migration_review --workflow artifacts\task-acceptance-v2\workflow --published-root artifacts\task-acceptance-v2 --out artifacts\task-acceptance-v2\human-review-scope
```

Core preparation is standard-library Python, offline and does not fetch upstream. It uses the prepared fixed source locally or the original checkout's read-only source through the shared git-directory location. Publishing requires .NET SDK 8+ and Microsoft.Data.Sqlite 8.0.31; ordinary integrated scorer/browser calibration additionally requires the declared Docker/runtime/browser dependencies. No model time is needed for these references. The initial measured HTTP/SQLite reference workflows took approximately 1.4 seconds each, excluding publish, browser, scorer and packaging; those durations are apparatus observations, not model-Run resource estimates. The model time ceiling proposed by the task register is 1200 seconds per arm; the coordinator prospectively fixes actual runtime/repetition allocation and affordability.

## Pending human review

`migration_review` binds source/data/public request/task profile/requirements/oracle/reference/template/code and workflow evidence hashes into `technical-scope.json` and `human-review-pending.json`. It refuses to bind a changed requirement ledger or changed workflow producer/template. The human template remains `not_run`, with no reviewer or timestamp. Actual human approval must record who checked which scope and what they observed in a separate receipt; automated execution cannot change that status.

Start two disposable reference copies for a human to operate:

```powershell
.\research\Start-MigrationReview.ps1 -RepoRoot $PWD -PublishedRoot "$PWD\artifacts\task-acceptance-v2" -OutputDirectory "$PWD\artifacts\task-human-review-v1"
# A: http://127.0.0.1:5051   B: http://127.0.0.1:5052
.\research\Stop-MigrationReview.ps1 -ReviewDirectory "$PWD\artifacts\task-human-review-v1"
```

The helper opens hidden owned app processes, records PID/generation/absolute application path and exact initial DB/assembly hashes, passes no gateway credentials, and keeps copied databases and logs. The stop helper checks both path and process generation and stops only those owned instances. Do not use another Run's process or database for review.

The helper was exercised on a second disposable pair at ports 5053/5054. The initial stop safely refused a timestamp mismatch because PowerShell's JSON reader materialized an ISO UTC string as a DateTime and a later culture conversion lost its timezone. The corrected stop keeps the date type/timezone, stopped exactly that owned pair, and left the human-review pair at 5051/5052 responding with HTTP 200. `artifacts/task-human-review-stopcheck-v1/stop-receipt.json` binds this result to the stop-helper hash.

Required human judgments are the source/data-defined arithmetic, quantities/current prices, visible decrement/removal without a refresh, invalid versus valid address checkout, existing identifiers/historical amounts versus current amounts, and credibility of this explicitly narrow source/data preservation scope. The pending template gives exact steps and amounts for each. Required human acceptance, independent applications and held-out task reservation are not replaced by successful automated controls. Issue #22 remains open and combined acquisition readiness must remain blocked while its mandatory human confirmation is missing.

## Subsequent independent family addition

The v2 candidate register adds an independently sourced and executed education
family with two nested variants; see [the education task report](research-repair-education-tasks.md).
The one-family counts and held-out limitations above describe the preserved
Music Store acceptance unit and old plan. The new selected scope has two families,
not four independent tasks, and prospectively reserves education for future model
outcomes while exposing reference/oracle/calibration work. Human confirmation
remains not_run and mandatory. Ordinary evaluator/browser integration and the
coordinator's final start gate are recorded separately.
