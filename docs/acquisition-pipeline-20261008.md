# Acquisition and evaluation pipeline

The user explicitly requested removing non-data-quality gates, retrying failed
acquisitions with fresh identities, and overlapping evaluation with subsequent
model runs on 2026-10-08 JST. The prior campaign repeatedly traversed the entire
predecessor chain and waited for evaluation/archive closure before dispatching
another wave. Wave09 then stopped before any worker allocation because its
proof-service ping timed out. That administrative dependency is removed from
the new operational path; old plans, attempts, STOP records and outputs remain.

`research.acquisition_pipeline` runs two generation jobs (two arms each) and one
evaluation/archive job. Evaluation runs in a separate Python process so pinned
browser environment activation cannot change the model workers' environment.
At most four completed pairs queue for evaluation; this bounds disk growth.
The next generation does not depend on prior quality, publication, or archive
closure. Actual owned generation resources must be stopped before its lane is
reused. Each pair retains its independent resource observer and resource limits.

The inherited complete ledger, usage and current plan are snapshotted once at
handoff. Each new epoch validates fixed assignments, runtime/evaluator/browser
pins and current controller hashes without recursively revalidating historical
plans. Each current Run still checks input identity, native/gateway evidence,
resource ownership, and frozen generated output. Current cumulative usage and
the original campaign budgets/time origin are retained. Unknown usage remains
explicit beside the observed lower bound.

Generation faults preserve every attempt and reason. Retried slots receive new
UUIDs in a fresh epoch; completed low-quality results are never retried. Saved
evaluation faults get a bounded retry using a new scoring sequence and retained
old evidence; they do not cause model resends. Adoption reuses the existing
browser/evaluator identity and coverage checks, including valid product build
failure with missing dependent quality. No intermediate Release is performed.

`config.json` is the current operational plan, `events.jsonl` records reservations,
generation, evaluations and acceptance, and each pair retains acquisition and
evaluation receipts. `heartbeat.json` is only a progress projection. A `STOP`
file in the pipeline root stops further owned execution. The process holds an
exclusive owner lock. On restart, completed saved evaluations are reconciled;
an interrupted acquisition with uncertain live ownership requires recovery
before starting fresh attempts.
