# Catalog input connection and four-Run technical pilot

The user accepted deletion-evaluator completion on 2026-09-20 after PR #12
merged as `8c1d10b9187f7a8af84c3393854aff24688581ce`. This work implements
the [adopted two-condition contract](ms1-catalog-return-two-condition-spec.md)
and the explicitly authorized technical pilot. It does not reopen evaluator
acceptance or change the historical 24 artifacts and their results.

## Installed connection

`catalog-expanded` and `catalog-compact` use the same `catalog-return` method.
Both copy the pinned legacy snapshot, run the authoritative deterministic
extractor, and expose identical files under `/inputs`. Only expanded appends
`raw-first.txt` after the common JSON in the initial user message. No condition
name or behavior advice is added to the model message.

`deepseek-catalog-v1` retains OpenCode 1.17.11, DeepSeek V4.1 Flash, the existing
provider, 1,800-second Run and 600-second provider deadlines, concurrency one,
and the existing compaction settings. Its separate artifact namespace is
`artifacts/runtime/MS1-001-catalog-v1`; old runtime locks are not replaced.
The catalog runtime feeds the prompt to OpenCode on standard input. A worker
preflight verifies reads, read-only mounts, source and derived-file hashes, and
two identical retrieval ranges under the actual agent UID before launching
OpenCode in that same container. Preflight reads are labeled harness activity
and excluded from model retrieval counts.

The gateway verifies the expected initial prompt in exactly one user message,
including the expected number of source packets, after normal serialization
and before external dispatch. The original prompt, file manifests, request
bytes, request hashes, native session, provider responses and cleanup records
remain available in each Run.

## No-model verification and launch

`research.catalog_connection_probe` uses the production controller, worker,
OpenCode and gateway with a container-local mock upstream and a synthetic
credential. It captures upstream request bodies and asks the ordinary bash
tool for the same source range, then checks its presence in the next request.
It compares complete initial request bodies after removing only the expanded
packet. It also compares worker file/permission/retrieval records. Synthetic
usage and probe executions are excluded from the live pilot.

After this gate passes, `research.catalog_pilot freeze` saves a four-slot
schedule containing one expanded/compact pair and one compact/expanded pair.
The order of the two pairs is randomized once and recorded before dispatch.
The plan fixes source/code/profile/build identities and the probe reference.
`research.catalog_pilot execute` runs the ordinary harness CLI serially with
fresh session, state and workspace for every slot. A durable dispatch journal
precedes each Run. Existing or uncertain dispatches cannot be silently replayed.

There are exactly two slots per condition and no replacements. Product failure
is retained and does not itself stop the schedule. Authentication, model,
input, source-integrity or cleanup problems stop further model execution for
diagnosis. Evaluation recovery uses the same frozen artifact and preserves
the earlier result. No model fallback, new purchase or credential change is
authorized.

## Interpretation

This cohort checks technical connection, execution, measurement, browser
evaluation and preservation. It is not a test of efficacy or noninferiority.
Report all four assigned slots, including unstarted or technically incomplete
slots, provider input/output tokens and calls, known partial sums, per-requirement
outcomes, coverage and cleanup separately. Ordinary model rereading in compact
is an observed response, not a violation. Track source/catalog retrievals and
the retention of their large outputs in subsequent requests.

Passing generated products are not required for connection completion. Any
remaining technical mismatch makes the connection incomplete. A confirmatory
experiment's repetitions, primary comparison, quality criteria and stopping
rules will be fixed separately after this pilot.
