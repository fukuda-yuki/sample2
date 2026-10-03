# Next research phase: exact-bundle start and recovery

The current protocol is `research/protocols/source-information-two-families-20261003-v3.json`.
This prospective revision corrects static database delivery. The earlier v2
protocol and blocked bundles remain preserved. Tasks, scientific allocation,
source-presentation intervention, model settings and analysis are unchanged.
It compares initial permitted-source presentation (`preload - explore`) under
serial execution, using two fixed source families, two semantic variants per
family, 16 paired repetitions per variant: 64 pairs and 128 assigned slots.
MusicStore is the development/calibration family; Contoso enrollment is reserved
as the research held-out family before comparative outcomes. Its source, oracle
and compatibility reference are inspected and calibrated for basic acceptance;
this is not sealed-source secrecy or evidence of eliminated contamination.

Both families and their variants receive equal weight. Primary outcomes are
all-assigned full-contract pass probability difference and mean provider-reported
whole-Run input-plus-output token difference. Unknown quality stays unknown,
confirmed product failures remain failures, and missing token totals remain null.
Identification bounds and explicit sensitivity assumptions accompany the results.
Complete-pair analysis is secondary. There is no maintenance/noninferiority
margin, no joint success flag and no general migration-population claim.

The fixed 64-pair cap gives a normal quality-difference half-width of about 0.173
at discordance 0.5 under independent pairs; each 16-pair variant is much less
precise (about 0.346). Session ICC and missingness sensitivity weaken precision.
The implementation budget sums to at most 64 hours, excluding postprocessing
and public gates. Storage and account completion estimates are scenarios, not
guarantees. Two fixed families do not identify reliable random-family variance.
The earlier one-family protocol remains preserved and is blocked from acquisition.

All commands below run from the clean integration worktree:

```powershell
Set-Location 'C:\Users\mwam0\.copilot\repos\sample2\work\repair-integration-20261003'
$env:NODE_PATH = 'C:\Users\mwam0\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
$env:SAMPLE2_BROWSER_EXECUTABLE = 'C:\Users\mwam0\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe'
$env:SAMPLE2_MONITOR_ROOT = 'C:\Users\mwam0\.copilot\repos\copilot-agent-observability'
```

The executor applies the validated browser pin during serial scoring, recovery
and unsent-only continuation. A successful dependency preflight alone is not
evidence that a collector received its required environment. Release tags include
the frozen bundle hash, so technical sharing rehearsals and amended bundles do
not reuse a study pair's tag.

Do not copy an API key into these commands or environment settings. The existing
Windows User credential is read only by the existing gateway bootstrap. Worker,
scorer, generated app and monitor receive no credential. The dedicated technical
four-Run comparison is separate from this study and does not authorize acquisition.

Preparation freezes committed source bytes, four task profiles and per-task
runtime/evaluator bundles, source/data/oracle assets, actual intervention,
browser/Node/Python identities, assignments and exact acceptance receipts.
This action sends no model request and reads no credential. The current v3
ledger, bundle and recorded full environment check exist at the paths below.
This check-only command can be repeated and does not overwrite a receipt or
start a worker:

```powershell
python -m research.next_phase check --bundle .\artifacts\source-info-v3-prepared-20261003\bundle.json
```

A blocked check exits 2 and reports each missing acceptance separately. Basic
human oracle/workflow confirmation for both families is mandatory. An agent's
automated review cannot set `human_review=passed`. If a human review or accepted
artifact changes, retain the old ledger/bundle and prepare a new version with
the reviewed exact bytes. Do not edit a frozen bundle or its referenced ledger.
The current task profiles select `workspace-static-db-v2`. Final workspace
`.sqlite`, `.sqlite3` and `.db` files are submitted static assets; scratch and
runtime databases belong in `/tmp`. Associated nonempty WAL, SHM or journal
leaves collection unconfirmed. The collector records asset hashes and never
modifies a database. Frozen identity counts all files using the existing SDK
algorithm. Conditions without opt-in retain legacy collection. Historical
Preload lost its static copy under that legacy rule; its failed package and
evaluations remain unchanged and no missing historical file is reconstructed.

After an actual human reviews the exact assets, use a newly accepted ledger and
a new bundle directory. The following are future commands, requiring that
accepted ledger to be created first. For example,
with the final accepted ledger saved at the following exact path:

```powershell
python -m research.next_phase prepare --runtime deepseek-research-v2 --ledger .\artifacts\source-info-v3-acceptance-human-v1\ledger.json --browser .\artifacts\source-info-v2-environment-20261003\browser-pin.json --out .\artifacts\source-info-v3-prepared-human-v1
python -m research.next_phase check --bundle .\artifacts\source-info-v3-prepared-human-v1\bundle.json --out .\artifacts\source-info-v3-prepared-human-v1\environment-check.json
```

These future accepted ledger, bundle and approval paths do not exist yet.
Preparation uses a new output directory and cannot overwrite an earlier bundle.
If acceptance changes code or inputs, commit the change and update its affected
runtime/evidence before preparing the new bundle.

Only after all technical and human prerequisites pass, a separate user research
start instruction must be recorded in a new approval JSON with `authorized=true`,
`approved_by="user"`, the exact `bundle_sha256`, the original authorization
reference and a UTC `approved_at_utc`. No such instruction or approval is inferred
from repair completion, Issue closure, technical testing, commit or Push.
The following exact command starts **one pair only**, and fails closed until both
preflight and that approval pass:

```powershell
python -m research.next_phase execute --bundle .\artifacts\source-info-v3-prepared-human-v1\bundle.json --approval .\artifacts\source-info-v3-prepared-human-v1\user-start-approval.json
```

The short cohort root is `runs/source-info-v3`; attempts 4001 through 4064 and
immutable instances distinguish all 128 assigned slots. Each Run keeps its
ordinary 1800-second budget and 600-second provider timeout. No overlapping
implementations, no account/model fallback and no replacement Runs are allowed.
Provider-side cache remains naturally encountered on the same account; balanced
order does not prove absence of carry-over, day, quota or provider effects.

After both implementations stop, the controller serializes scoring, monitor
import and archives, then holds. A pair's public subset must be reviewed, remotely
verified, independently downloaded/restored/extracted with sockets blocked, and
its owned transfer copies cleaned before another execute invocation can start
the next pair. For pair 1:

```powershell
python -m research.next_phase_sharing stage --bundle .\artifacts\source-info-v3-prepared-human-v1\bundle.json --pair 1 --workspace .\artifacts\continuity-sharing-v1\pair-001
python -m research.next_phase_sharing share --bundle .\artifacts\source-info-v3-prepared-human-v1\bundle.json --pair 1 --workspace .\artifacts\continuity-sharing-v1\pair-001 --review .\artifacts\continuity-sharing-v1\pair-001\public-review.json
```

The second command requires an actual exact-inventory public review, including
secret/private-context scans, generated images and source licenses. A template
is not approval. A failed or uncertain transfer is reconciled without overwriting
remote assets. Saved finalization checkpoints recover cleanup without another
model request. Original Runs, evaluator attempts and raw provider records remain.

On interruption, stop and recover only existing owned instances:

```powershell
python -m research.next_phase stop --bundle .\artifacts\source-info-v3-prepared-human-v1\bundle.json
python -m research.next_phase recover --bundle .\artifacts\source-info-v3-prepared-human-v1\bundle.json
```

Recovery never starts a worker. If a serial pair has a reserved but unsent second
slot, an explicit resume after unchanged preflight can start only that immutable
unsent instance. Dispatched, uncertain or lost instances are never replayed:

```powershell
python -m research.next_phase resume --bundle .\artifacts\source-info-v3-prepared-human-v1\bundle.json --approval .\artifacts\source-info-v3-prepared-human-v1\user-start-approval.json
```

Analysis reads identity-bound terminal receipts and versioned normalized usage,
checks stopped gateway originals and rejects changed/foreign usage. It does not
accept arbitrary imported rows:

```powershell
python -m research.next_phase_analysis --bundle .\artifacts\source-info-v3-prepared-human-v1\bundle.json --out .\artifacts\source-info-v3-prepared-human-v1\assigned-analysis.json
```

The old 100 pairs retain their original protocol, raw records, verdicts and ZIP.
The old 320-pair remainder is never resumed by these commands. No new research
dispatch is performed during this repair task.
