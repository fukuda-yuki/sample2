# Migration evaluation repair (Issue #21)

Evaluation contract `1.3.0` applies only to `MS1-CONT-A` and `MS1-CONT-B`.
They are semantic variants nested within one Music Store source family. The
historical `1.1.0` and `1.2.0` records, contracts, products and ZIPs retain their
original meaning and bytes; no historical cohort is rescored by this repair.

The public contract and independent source/task authority are owned by Issue
#22. The versioned ledgers map all 31 normative requirements to 33 implemented
checks, expected outcomes, source/public authority and explicit coverage. The
initial operational SQLite database and independent Decimal oracle are private
evaluation assets; neither is a substitute for source inspection in the public
request. Only the operational database is also a legitimate migration input.

The `1.3.0` ledger inherits the `1.2.0` HTTP/static checks, explicit order-number
marker and other-session denial. Browser removal actions `C-015`/`C-016` remain
mandatory in ordinary `score_run`, composition and aggregation. Uniform `8.99`
price assertions are replaced with source-defined effective per-unit prices;
historical order unit prices remain unchanged. Added critical `R-030`/`C-031`
observes every frozen initial row/column at startup and after restart, plus the
stored quantities, prices and totals for three representative checkout orders, and the same executable importing the snapshot on a missing database path. All nine missing-address cases and mixed-case promo acceptance are observed. Added critical R-031/C-032 checks cross-session removal integrity; the browser checks include the visible cart summary.
Initial oracle/database disagreement is an evaluator fault; lost product rows,
changed historical amounts or incorrect new-order details are product failures.
Confirmed startup failures survive a later restart or collector fault.

The calibration program is `inner/calibration/migration-chain.py`. Its exclusive
output binds the exact executable bundle, image, collector/composer/harness
hashes, input/asset hashes, Node/Chromium pin and the predeclared finite case
manifest. It uses ordinary isolated scoring, real browser actions, the same
composer and owned cleanup, with no provider/model calls. Human review remains
`not_run`; this automated receipt never establishes ordinary-user acceptance.

The finite case manifest must be fixed before execution: raw-SQL/minimal and
EF/MVC allowed implementations, independently prepared variant-B calibration
controls, historical-row deletion, missing JavaScript update, unsupported UI,
collector unavailability with a prior critical product failure, and injected
cleanup-receipt failure after actual owned cleanup. Three extra targeted cases reject missing initial-data import, a stale browser cart summary and foreign-session removal, corresponding to newly exposed public-contract gaps. Calibration controls are
withheld from evaluator implementation, not a held-out research application.
Do not change expectations after observing results. Repairs require new
versioned receipts, preserving the failed receipt.

`human_review=not_run` blocks the combined acquisition-ready claim. The concrete
human checklist must confirm (1) initial album/customer/order identifiers and
historical quantity/price/total authority, (2) source policy A/B unit rounding,
(3) normal browse, add twice, click remove twice and visible cart totals,
(4) address checkout and stored order details, (5) restart continuity, and
(6) whether the specified legacy defects should be corrected. Record the
person, timestamp, reference/asset hashes and observations; unperformed items
remain `not_run`.

Limits: a single family; representative routes and quantities; prescribed DOM
markers and standard controls; no universal defect-detection, pre-migration
legacy-runtime equivalence, accessibility, concurrent-user load, authentication,
payment, StoreManager CRUD or migration-quality noninferiority claim. An
unsupported control yields incomplete coverage, not a manufactured failure or
pass. Operational cleanup status is separate from already saved product quality.

The initial deep-directory calibration found a required SQLite content file removed by normal collection and a Win32 long-path cleanup receipt failure; failed receipts are retained. The reference package now tolerates absent output SQLite and imports the legitimate read-only input. Cleanup uses Win32 extended paths and has a regression check exceeding 260 characters. Receipt results and the final exact-chain identity are appended after execution.
