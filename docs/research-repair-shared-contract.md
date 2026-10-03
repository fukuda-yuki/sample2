# Research repair coordination contract (2026-10-03)

Base: `3dba038bced6c0a525098245a3f66d162f1b15bf`. The dirty original checkout and all old research records remain unchanged. Current Issue bodies and comments were fetched before implementation and are saved locally in `artifacts/research-repair-20261003/issues-at-start.json` in the original checkout.

## Ownership and handoffs

- A (#21): `inner/evaluator`, `inner/spec`, `inner/browser`, calibration programs, `outer/harness/evaluate.py`, `browser_cart.py`, `aggregate.py`, related evaluation tests and `docs/research-repair-evaluation.md`. Do not edit B's reference/task files or C's lifecycle/profile files.
- B (#22): new task assets/reference implementations, task register, independent oracle/workflow checker, new task profiles and task-input preparation module, task tests and `docs/research-repair-tasks.md`. Do not edit existing `inner/fixtures/reference` without agreement with A. Agree the task/evaluator interface with A before changes that cross it. Request profile/runtime hooks from C; do not concurrently edit `profiles.py` or `runtime.py`.
- C (#20 + #23): `outer/harness/runtime.py`, `run.py`, `usage.py`, `machine.py`, `profiles.py`, gateway/worker/security changes, `research/catalog_execution.py` and necessary new pair execution module, lifecycle/usage/pair tests and `docs/research-repair-execution.md`. Preserve legacy read semantics. Coordinate evaluation interfaces with A and new input hooks with B.
- Coordinator (#24): new prospective protocol/controller/preparation, design calculations, acceptance ledger, human review handoff, final integration and launch guide. Do not modify A/B/C owned files until handoff or explicit agreement.

## Shared execution evidence

Every assigned slot binds cohort/plan hash, pair, slot, display Run ID, immutable `run_instance_id`, ownership, task/intervention/runtime hashes before child startup or transmission. A call binds instance plus durable call ID and raw input hash. Dispatch intent is not observed transmission; observed transmission is not provider acknowledgement; a response or DONE marker is not complete usage. Use explicit known-no-send / observed-send / unknown evidence and null complete totals for incomplete usage. Keep observed partial cumulative sums, raw amounts and conflicts, and bind derived record hashes. No automatic redispatch of an assigned dispatched instance, including missing directories. Product failures remain observations; infrastructure/storage/identity faults stop new dispatch. Never pass the credential outside the existing gateway-only path.

One manager holds the existing OS lock, permits at most the two slots of one pair, persists dispatch first, accepts result order by identity, preserves each stopped Run immediately, then performs heavy scoring/monitor/archive/compression serially after both implementations have stopped or explicit safe terminal evidence. Unconfirmed stop blocks ordinary collection/postprocessing/public completion. Existing publication/restore/owned-cleanup gate blocks the next pair. Run-level worker concurrency remains 1; pair scheduling is separate and bounded to 1 or 2.

## Task and oracle interface

A and B agree and publish versioned public request, ledger, expectation/authority map, selected source families and semantic variants before final calibration. Variant-specific answers live in old code/data or private oracle, never in the common public request. Variants are nested within a family and never count as independent applications. Existing identifiers, relationships, nonuniform amounts, order/quantity semantics, restart continuity, preserved behavior and corrected old defects must have executable observations. A single reference implementation is not an independent oracle; B provides a separate checker or manually derived expected values with source authority, and A calibrates multiple allowed implementation forms, defects and withheld controls through ordinary `score_run`, browser collection/composition and cleanup. New contract version must explicitly retain browser coverage.

Human review is `not_run` until a human actually performs/records the required basic checks. Automated/AI review remains separate. Prepare a runnable reference and concrete checklist before requesting only missing judgments. Missing human acceptance blocks combined research readiness.

## Validation and scientific boundary

Predeclare finite relevant cases; preserve failure receipts and do not repeat passed checks without new reason. Mock upstream and normal worker paths first. A live 1/2 comparison, if possible, is a distinct technical cohort with fixed run count/order/limits/stop/decision rules recorded before dispatch. No new research Run or old 320-slot continuation is authorized. Keep old originals/ZIPs/plans/verdicts. A serial next study is acceptable if paired technical acceptance remains blocked; serial and paired measurements must not be pooled.

Each owner leaves meaningful commits. Integration uses `git merge --no-ff`, never rebase/squash/amend/reset. Evidence is versioned under a new local output directory and final code is checked after merges. Issue comments record demonstrated acceptance, not merely code presence. Issues stay open while mandatory acceptance is missing.
