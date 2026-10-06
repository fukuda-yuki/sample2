# Repaired evaluator parallel acquisition

`research.repaired_campaign` is a supervised acquisition controller. It keeps the
accepted Music 1.6.0 and Education 1.1.0 scoring contracts, input assets, model
settings, and original research allocation. It fixes 100 logical pair slots
(25 of each task), independently of later technical acquisition attempts.

The top plan binds the accepted baseline plan, current committed controller
bytes, the user's authorization, the logical slot order, and finite limits.
Each administrative epoch uses an ordinary repaired-main plan with 200 fresh
Run UUID reservations. A reservation is never counted as a model transmission.
Only an immutable, journaled wave can admit its selected one or two pairs.
The first occurrence of every logical slot follows the original fixed order.

The campaign owner permits at most two pairs/four implementation Runs, with at
most four observed concurrent HTTP requests. One OS lock covers the supervisor
and another covers the campaign worker across all epochs. A retained Windows
process handle detects supervisor loss; STOP closes all admitted owned UUIDs.
Scoring/browser environment activation is serialized across the two pairs,
because the accepted browser adapter temporarily changes process environment.

The first budget is 300 paired attempts/600 Run attempts, 90,000 observed
requests, 4.5 billion observed input+output tokens, 1,080,000 accumulated Run
seconds, and 1,350,000 elapsed campaign seconds. A wave has a 7,200 second
external wall and the unchanged 1,800 second per-Run/600 second provider limit.
These are observed operational ceilings, not provider hard quotas. Resource
floors remain 8 GiB free disk and the accepted host/Docker memory thresholds.
The new campaign directory inherits NTFS compression for both arms; every
original byte remains retained and all old acquisition directories are unchanged.
Recovery delays are 60, 300, 900, then 3,600 seconds, bounded by the same budgets.
No purchase, paid fallback, account change, or balance spending is allowed.

Both arms of a pair remain attached to the same acquisition attempt. Fully
observed quality failures (including zero) are valid data. A product prerequisite
failure with incomplete numeric quality is retained as a valid product-failure
observation with quality unknown; it is not relabeled zero or replaced for a
better score. Numeric-complete pairs are counted separately from valid pairs.

Technical failure recovery first reconciles actual transmission and exact owned
closure, then attempts same-version assessment of saved immutable artifacts
under new assessment IDs. Original acquisition bytes, raw usage and failed
evaluations are preserved. Only independently evidenced provider/infrastructure/
evaluator failures can authorize an entirely new paired attempt at the same
logical slot. Timeout or generated-code failure alone is insufficient. Ambiguous
transmission remains held until reconciled. All usage, including failed attempts,
belongs to the campaign; assessment work does not fabricate model usage.

Normal waves require the existing actual Release, anonymous download, restore,
offline extraction and owned-copy cleanup gate. Technical failures use a separate
factual preservation gate, never a fabricated successful acquisition gate. Exact
public-byte review excludes credentials and private evaluator materials. Old
STOP markers are immutable; a verified recovery closure may acknowledge their
hashes through an append-only clearance. A new wave fault produces a new STOP
event and cannot inherit an old clearance.

The controller is deliberately supervised: the researcher reviews public bytes,
executes explicit wave/recovery operations, and verifies the ledger. It does not
hide faults behind unattended retries. Completion requires 100 adopted logical
slots, preserved initial-slot failures/missingness and every attempt, real
publication gates, and verified absence of owned model/observer resources.

Normal observer retirement now requires the owned terminal proof and a healthy
observer while holding the watch lock. The observer is removed from active
checks before shutdown, and its shutdown acknowledgement is still validated.
Unexpected exits, missing proofs, fault latches and bad acknowledgements retain
their stop behavior. The first watch exception records its message and traceback
before STOP; a failure to write that diagnostic cannot suppress STOP.

Fault recovery inventories use the preservation layer's Windows native paths,
including files beyond the ordinary path length limit. Historical assessment
inventory and readiness implementations remain unchanged. Recovery records pin
the clean committed recovery checkout separately from the acquisition checkout;
public evidence distinguishes both commits and retains acquisition end reasons.
An unsuccessful recovery directory is retained and a retry uses a new directory.

An explicit controller succession preserves the same campaign ID, 100 logical
slots, settings, budgets, original start time, attempts, adoptions and usage.
It requires every old wave closed and owned resources inactive, then permanently
fences the old root with a new stop event. Immutable history binds the old ledger,
all old epoch UUID reservations and closures. The successor uses a separate clean
committed checkout and storage root, and excludes all previously reserved UUIDs.
Succession does not reset the denominator or resource and elapsed-time budgets.

Within one controller operation, a scoped validation context reuses a successful
deep check of the same predecessor closure. Its plan, wave and closure reference
bytes are rechecked before reuse. History, ledger, retirement, STOP, ownership and
current usage checks remain fresh. The context is discarded on operation exit;
the next operation performs a new complete predecessor check. Failed and cyclic
checks are never memoized as success. This avoids repeatedly replaying the same
historical readiness chain during a single admission without weakening live
fault detection or carrying proof trust across operations.

An optional `research.proof_session` service now shares closed evidence proofs
across controller operations and their subprocesses. It is Windows-only, owned
by a distinct live process handle, finite (four hours by default, eight hours
maximum), and limited to 512 in-memory entries. There is no disk success cache:
each fresh service validates the actual evidence again. The private reference
contains a local pipe authentication key and must never enter Git or a Release.

Every file read by a shared proof is held with Windows sharing that denies writes
and deletion. Directory identity handles and name-change notifications reject
replacements, additions, and junction changes. Negative cleanup paths are
explicit dependencies. One persistent validation thread owns those notifications
across connections; separate status connections stay responsive. Source inventory
and module bytes bind clients to the service. Read-only Git/Docker probes replay
on reuse. Git committed-file checks use one binary `cat-file --batch` process
with strict framing and unchanged SHA256 comparisons instead of one per file.

Only readiness, immutable phase definitions, normal publication gates and fully
closed recovery evidence can be shared. Recovery evidence remains uncached until
its administrative wave closure exists. Current history/ledger, STOP, admission,
UUID reservations, dispatch, usage, ownership and leases are outside these
proofs. Current epoch tree checks remain fresh. Closed gate validation checks its
exact original Run roots without repeatedly walking unrelated historical pairs.
The old unrestricted clearance success set has been removed.

Start the service as a hidden child of a finite supervisory process, after the
clean successor source has been pinned. Use `python -B -X utf8 -m
research.proof_session serve <new-private-reference.json> --owner-pid <live-owner>
--seconds 14400`. Pass `--proof-session <reference>` to `research.repaired_campaign`
and `research.campaign_launcher`; the latter propagates it to its owned worker.
Python administrative operations can use `proof_session.connected_session(ref)`.
The launcher rejects an unpinned proof module. `proof_session check <reference>`
checks current service/guard liveness; `proof_session stop <reference>` releases
the owned service. Owner exit, expiry, source/evidence changes or proof failures
invalidate reuse. Never renew a reference or replace an invalid proof with a
persisted success flag. Finish owned stop/closure, then create a new finite
service and fully validate again. Stop helpers do not depend on this service.
