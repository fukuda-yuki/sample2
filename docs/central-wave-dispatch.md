# v5 remaining-slot central wave dispatcher

This is a separate prospective execution phase for original pairs 6–100. It
retains the old bundle, original 200 slot/instance mapping, first ten dispatches,
all five completed gates, prior failures and scores. It neither edits the v5
scientific protocol nor treats concurrency 4/8 as previously accepted. New
source pins, an operational policy and exact-phase user approval are required.

`research.wave_plan.build` creates an offline manifest. Its immutable references
include the old bundle, old journal and operational policy. Original assignments
are copied exactly. Fixed responsibility counts are 24/24/24/23, with variant
counts differing by at most one between owners. Dispatch preserves original pair
order and each pair's arm priority. Two-pair blocks begin at pairs 6/7; subsequent
waves use one or two adjacent predefined blocks. The final tail may be one pair.
There are no additional pilot, replacement or outcome-selected slots.

`research.wave_dispatch.Dispatcher` owns the original cohort OS `dispatch.lock`
through an entire `session()`, including serial heavy processing and publishing.
The durable `_control/phase-handoff.json` also fences legacy entrypoints in this
new source version. Each process/worktree must target the same canonical cohort
batch; copies of control files are not independent acquisition authorities. A
stale old source checkout must never operate this handed-off cohort. The parent
controller is responsible for installing the new source at every permitted
entrypoint and excluding unversioned legacy launchers.

The phase uses `_control/central-wave-pair6-100-v1/wave-journal.jsonl`; the old
`pair-journal.jsonl` stays byte-identical. Per-Run `plan_sha256` remains the original
bundle hash, while `phase_sha256` independently identifies the new regime. Every
phase receipt, gate and resource observation retains these bindings. The first
wave is at most two pairs/four Runs. Escalation also requires `escalation_healthy`
from the frozen operational policy after the first wave's gates. If this flag is
false and ordinary health holds, waves remain at four Runs. The exact snapshot
allowlist cannot contain quality, verdict, arm effect or token outcomes. Full
resource/HTTP observations are retained as hash-bound evidence files.

No new work is submitted into a wave when its Runs finish early. Each stopped
Run immediately fixes originals through the unchanged implementation harness.
After every wave Run stops and fixes originals, postprocessing and pair
publication/anonymous restore/offline extraction/owned cleanup run serially.
Every wave pair gate precedes the next wave. `publication_ready(number,current)`
can stage an owned public copy and return false until exact review is available;
this records neither remote intent nor an operational fault. `publish` then
returns the ordinary generic gate receipt with an additional `phase_sha256`.
It must avoid legacy `pair_context`, old journal mutation and recursive cohort
lock acquisition. Publishing callbacks reconcile existing exact remote bytes and
saved finalization after interruptions, instead of blindly reuploading.

`HarnessAdapters` supplies original real `profiles.create`, guarded model
implementation, browser postprocessing and distributed owned shutdown. A
separate immutable preparation view is optional and requires an original-bundle-
bound witness and `validate_preparation(view,phase)` before prepare/verification.
Only this view creates new frozen evaluator assets; original worker prompt,
task/intervention/runtime profiles, time budgets, model and evaluator criteria
must retain the lead's declared equivalence. Root runtime/gateway/controller
bytes stay unchanged. Existing original Runs and scores are never rescored here.

`supervise(active_bindings)` is polled by the central manager at most one second
apart while implementation futures remain active. The callback handles the
frozen ten-second resource cadence/age bounds and returns a fault reason or
`None`. A fault first closes dispatch durably; all owned active gateway fences
are initiated concurrently before waiting for worker stops. Each gateway ACK,
fallback and unknown state remains explicit. The returned effective HTTP stop
time requires all gateway fences confirmed; it is distinct from the host stop
decision. Past confirmed stopped Runs are not refenced. Journal/storage failure
still initiates owned shutdown using the in-memory ownership table and records
evidence loss honestly.

Recovery never repeats a dispatched or ambiguous send. It attempts every owned
uncertain Run, retains original terminal receipts and allows serial processing
only after confirmed stop/original fixation. Uncertain postprocessing needs a
durable same-instance result receipt; interrupted publication uses explicit
reconciliation. `resume_unsent` requires exact journal and reserved instances,
objective health and the existing user's phase authorization. Dispatched peers
remain stopped. `clear_reconciled_stop` requires all wave gates, current health,
the exact journal/stop hashes and a recovery decision reference, preserving the
old stop record. A crash before send intent may reuse only a complete same-phase,
same-instance preparation demonstrably without `started_at` or runtime state.

The API has no live CLI or default credential/model/publication path. The parent
must freeze and wire the resource monitor, exact public review/publisher,
preparation-view validator and scientific-start approval before launching.
Local test fixtures exercise bounded concurrency and crash boundaries without
Docker, credentials, API requests, scoring or remote publication. Dispatch-to-
confirmed-stop peak is reported separately from actual HTTP overlap; a local
fixture cannot establish real provider or host acceptance.
