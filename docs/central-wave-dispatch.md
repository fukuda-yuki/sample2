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

## Probe-only successor phase

`wave_plan.build_v2` admits only the fully closed v1 boundary at pairs 6–11.
It holds the canonical cohort lease while freezing the predecessor phase, journal
and six gate references, verifies all original 22 instances stopped and fixed,
and checks raw/snapshot bytes against their original implementation receipts.
Missing gates, uncertain sends or changed evidence reject the handoff. Old
source pins remain historical; the new phase pins its own clean source commit.

The v2 manifest retains the original bundle and all 200 identities, assignments,
inputs, budgets, evaluation criteria, preparation view and operational policy.
Only original pairs 12–100 remain eligible, preserving their original order,
priority and responsibility owners. Waves contain the fixed blocks 12/13,
14/15 and so on, with pair 100 last; maximum concurrency is four Runs and
escalation is disabled. No wave refill or replacement instance is supported.

Only the private probe implementation may change. The monitor bytes must retain
the predecessor hash at a separate path. A hash-bound nonlive acceptance receipt
(`resource_probe_only_v2_nonlive_acceptance`) binds both probe hashes, unchanged
monitor and policy hashes, `fail_closed_unchanged=true`, `model_called=false` and
`run_created=false`. The controller does not infer acceptance from Run outcomes.

`wave_dispatch.handoff_v2(repo, phase_path, approval)` exclusively creates
`_control/phase-handoff-v2.json`, references the unchanged original handoff file,
and requires exact new-phase user authorization. Existing different handoffs
cannot be overwritten. Current-version entrypoints reject the old phase permit
after the successor handoff. The v2 journal is separate at
`_control/central-wave-pair12-100-v2/wave-journal.jsonl`; v1 remains readable and
byte-identical. Serial publication retains original plan bindings and adds the
new phase hash and predecessor phase/journal hashes to public metadata.

## Future v3 cause-condition-gated successor

This source candidate does not build or adopt an actual v3 phase. The retained
174-instance hold persists until the lead supplies a valid exact recovery
decision. Technical finite checks or a successful synthetic soak cannot create
that decision. No helper or historical phase is changed by this source patch.

`wave_plan.build_v3` takes a closed v2 predecessor and the keyword arguments
`source_commit`, `source_pins`, `resource_monitor`, `resource_probe`,
`finite_acceptance`, `actual_soak_verification`, `post_soak_independent_review`,
`post_v2_boundary`, `hold_boundary`, `revised_hold_instruction`, and
`recovery_decision`. All acceptance arguments are immutable path/SHA references.
Only the exact reviewed probe SHA
`5efb52edd48f37713b623df46d01ebbd89e2e3321c6548fe1ac2982bd97c9354`
and unchanged monitor are supported. Missing or modified final evidence rejects
the builder. The original global200 identities remain unchanged: only pairs
14–100 (174 instances) are eligible, responsibility counts 21/22/22/22, original
order and owners retained, maximum four Runs, no escalation or refill.

The validator recursively preserves v2 pairs12/13, v1 pairs6–11 and original
pairs1–5. All 26 original stop/fix/raw/snapshot/result/gate proofs must remain
valid, and the same cohort lease excludes an active predecessor.
`handoff_v3(repo, phase_path, approval)` appends `phase-handoff-v3.json`, binding
the unchanged v2 marker and frozen phase/journal/gates. The shared guard validates
every v1/v2/v3 link and rejects missing intermediate markers, forged ancestry or
an old permit. Frozen source copies remain historical: permitted entrypoints
must use the installed current source, as for the preceding handoff. A later
fault fences only uncertain current-phase instances, never confirmed old stops.

The acceptance wrappers have these required contracts:

- `finite_acceptance` binds `candidate` and `unchanged_monitor` references and
  `all_native_expected_decisions_passed=true`.
- `actual_soak_verification` has kind
  `actual_nonmodel_soak_bounded_evidence_verification`,
  `scheduled_samples=180`, `controlled_stop_observations=3`,
  `owned_fixtures_created_started_stopped_removed=8`,
  `all_original_references_checked_unchanged=true`, 26 original sent instances,
  174 remaining unsent, `formal_research_resume_authorized=false`,
  `historical_cause_resolved=false`, `model_called=false`, and immutable
  `protocol`, `attempt`, `result`, `ownership` and `command_ledger` references.
  The result must report 180 successful scheduled observations, three
  transitions, empty cleanup errors and the exact protocol hash. Protocol
  probe/monitor/original-bundle hashes must match the phase. Its retained source
  commit belongs to the actual soak (6eb source), not the later phase code.
- `post_soak_independent_review` has kind
  `actual_nonmodel_soak_independent_evidence_review_v3`,
  `operational_soak_verified=true`, `historical_cause_resolved=false`,
  `formal_174_hold_remains=true`, and exact `actual_verification`, `protocol`
  and `result` references. It is advisory technical evidence, not permission.
- `post_v2_boundary` has kind `quiescent_pre_v3_boundary`, timezone-aware `at`,
  exact predecessor `phase`, `journal`, `gates`, `actual_sent=26`,
  `all_stopped_fixed=true`, zero active Run containers, and successful recovery
  exit. This later bookkeeping timestamp is not a new permission boundary.
- `hold_boundary` references the original
  `quiescent_post_v2_recurrence_boundary` with its preserved timestamp, same
  phase/journal/gates, 26 stopped/fixed, all13 gates complete, 174 unsent and
  `new_research_dispatch_held=true`. `revised_hold_instruction` references the
  exact retained parent instruction that imposed the current hold.

`recovery_decision` is stored as `resource_collector_acceptance`, kind
`prospective_resource_fault_recovery_decision_v3`. It must set
`formal_remaining_dispatch_authorized=true` and `cause_condition_satisfied=true`,
retain the historical-cause Boolean, and bind the exact new source commit,
original bundle hash, predecessor journal hash, unchanged policy hash,
probe/monitor hashes and all named acceptance/boundary references above.
Its `acceptance_mode` is one of:

- `verified_mechanism_resolution`: historical cause must be resolved true,
  supported by an immutable `mechanism_resolution` reference of kind
  `verified_resource_transport_mechanism_resolution`, with affirmative
  historical-cause status and exact predecessor journal/probe hashes. It also
  binds separate `causal_evidence` and `independent_review` references. The
  affirmative review has kind `verified_resource_transport_mechanism_independent_review`,
  status `passed`, historical cause resolved true, the same causal evidence,
  and exact predecessor journal/probe hashes. The retained false advisory
  post-soak review cannot be repurposed as affirmative mechanism evidence.
- `parent_explicit_revised_condition`: requires a newly received
  `parent_instruction` reference of kind
  `parent_explicit_revised_resource_fault_condition_instruction`,
  `authority=parent`, `received_after_hold_boundary=true`, exact old
  `hold_boundary` and `revised_hold_instruction` references,
  `revises_existing_hold=true`, exact174/original-bundle/journal bindings, and
  an exact `message` equal to decision `parent_instruction_verbatim`. Its
  timezone-aware `received_at` must follow the original hold boundary, even
  when received before the later final bookkeeping boundary. Parent authority
  is recorded as parent authority and is not represented as human review.
  Historical cause may remain false. Any affirmative historical resolution
  still requires mechanism evidence.

The lead preserves actual received-message provenance; the builder cannot infer
a new instruction from a soak or manufacture one. A separate exact-phase user
authorization is still checked at campaign entry. Public v3 metadata adds only
ancestor phase hashes and acceptance/soak verification hashes; private instruction
text is not published. All heavy stages retain the existing global serial barrier.

V3 validation checks every listed immutable leaf in the finite acceptance and
actual soak/review wrappers, including the independent review's input references.
Exactly 183 unique sequential raw/monitor pairs are required: 180 scheduled
observations, then worker-stop, gateway-stop and all-stop. Current leaf hashes,
raw/sample equality, monitor sequences/session and exact result transition
references are rechecked on each validation. Hash reuse is confined to a single
validation call; no earlier successful validation can hide a subsequent edit.
