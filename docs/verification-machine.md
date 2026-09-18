# Modernization verification machine

This schema 2 path implements the plan approved on 2026-09-18. It adds an OpenCode
runner while retaining schema 1 Runs and the dummy/manual runners. The old
statement that `outer/` contains no model path describes the schema 1 prototype.
**Live delivery acceptance is pending.** See [current evidence](verification-evidence-20260918.md).

## Select task and intervention independently

Run commands from the repository root in PowerShell 7:

```powershell
python -m outer.harness.cli profiles
python -m outer.harness.cli profiles --task MS1-001 --intervention preload
```

| Directory | Responsibility |
| --- | --- |
| `outer/profiles/tasks/` | Source commit, public request, evaluator/ledger and success contract |
| `outer/profiles/interventions/` | How information reaches the initial input |
| `outer/profiles/runtimes/` | OpenCode version, model, compaction and time limit |

`explore` supplies the public request and readable legacy source. `preload` adds
20 fixed source files from the completed legacy application: controllers, domain
models and relevant views. Duplicate tutorial copies and the large sample-data
listing are excluded from the initial injection; all arms can still read them.
`explained` adds a description of existing processing to the exploration condition.
It supplies neither a target implementation nor private scoring details.

The public request, source commit and evaluator are common to all arms. Each Run
stores the three original profiles and their hashes, resolved condition, source
bytes, prompt, context mapping and evaluator bundle. Later profile edits do not
change a started Run. Changed frozen inputs/assets are refused. Schema 1
`--condition/--input` commands remain supported.

## Prepare

Prerequisites: Windows, Python 3.12+, PowerShell 7, Git, Docker Desktop with a
working **Linux engine**, and a .NET SDK for the existing monitor importer.
The live worker's OpenCode binary is prepared inside its image. Host OpenCode is
only required for the separate non-model CLI compatibility probe.

Before preparation, `docker info --format '{{.OSType}}'` must return `linux`.
If it times out or cannot connect, open Docker Desktop and use **Troubleshoot >
Restart Docker Desktop**, then wait until the engine is running and repeat the
command. If Desktop is using Windows containers, switch to Linux containers from
its tray menu. See the [official troubleshooting guide](https://docs.docker.com/desktop/troubleshoot-and-support/troubleshoot/).
If restart fails, retain the displayed error and the preparation failure record.
Clean/Purge data and Reset to factory defaults are destructive operations and
are not required by this procedure. When host recovery is blocked, the operator
needs these concrete steps; a Docker prerequisite alone is not a delivery result.

The Windows **User** environment variable `OPENCODE_GO_API_KEY` must already exist.
Do not paste it into commands, configuration files, issues or reports. The
controller reads that registry value and pipes it to gateway stdin. Worker,
evaluator, generated app and monitor processes use explicit environments that
do not inherit it. Worker configuration contains a non-credential placeholder.

```powershell
python -m outer.harness.cli prepare --task MS1-001
```

Preparation fetches the exact source commit and builds worker, evaluator and
gateway images. It records immutable image IDs, OpenCode 1.17.11, .NET SDK
8.0.425, evaluator bundle hashes and build provenance in
`artifacts/runtime/MS1-001/`. EF Core SQLite and Microsoft.Data.Sqlite 8.0.31
are cached before execution. Each preparation attempt has its own records.
Build from a clean checkout: the existing provenance gate rejects
`clean_worktree: false`. After implementation changes, commit the reviewed source
and use `prepare --rebuild`. A rebuild does not update started Runs.

The exact model is **`deepseek-v4.1-flash`**, checked against the
[OpenCode Go documentation](https://opencode.ai/docs/go/#endpoints) and public
`/zen/go/v1/models` response. The gateway sends only to
`https://opencode.ai/zen/go/v1/chat/completions`. A different response model
invalidates measurement. Main and auxiliary model selections are identical;
task/subagent tools are denied. All requests use the recording gateway.

Set `SAMPLE2_MONITOR_ROOT` to the existing `local-agent-monitor` checkout if it
is not at `~/Documents/Codex/copilot-agent-observability`. Its importer is used
as-is; this repository does not modify the monitor.

## Run, stop, score and compare

```powershell
python -m outer.harness.cli run --task MS1-001 --intervention explore --attempt 1
python -m outer.harness.cli status --run MS1-001-explore-001
python -m outer.harness.cli stop --run MS1-001-explore-001
```

`run` creates, executes, stops, collects, scores, links telemetry and packages a
Run. Default execution is sequential, with a 1800-second budget. Existing Run
IDs are never reused; choose a new attempt number after a repair. Diagnostic
budget changes belong in a separately named runtime profile before creation.
Use identical frozen conditions for all six final acceptance Runs.

Individual phases are also available:

```powershell
python -m outer.harness.cli create --task MS1-001 --intervention explained --attempt 1
python -m outer.harness.cli start --run MS1-001-explained-001
python -m outer.harness.cli collect --run MS1-001-explained-001
python -m outer.harness.cli score --run MS1-001-explained-001
python -m outer.harness.cli rescore --run MS1-001-explained-001
python -m outer.harness.cli aggregate
python -m outer.harness.cli compare --out runs/comparison.json
```

Global `--runs-dir <directory>` goes **before** the command. Use it for a batch
or restored Run directory. Comparisons keep changed task/runtime/evaluator
conditions in separate groups and preserve failed/unscored Runs and null usage.

The worker has read-only inputs, its own workspace/state, no research mounts,
no Docker socket and an internal network. Only gateway has an outbound network.
A preflight exercises these boundaries before dispatch. Scoring uses a separate
container with `--network none`, read-only frozen input and a fresh work/database
directory for every sequence. Host mock probes do not establish Docker isolation.

`stop` asks the active controller to shut down. If it crashed, an OS-held Run lock
allows recovery of that Run's labelled containers. Confirmation requires a
working daemon and stopped worker/gateway containers. Daemon unavailability is
`stop_unconfirmed`; collection is forbidden. Infrastructure/measurement failures
return a nonzero CLI status. A correctly scored failed implementation is a valid
quality observation.

## Measurement and preservation

`usage/raw/` keeps transmitted JSON, response SSE including partial streams,
durable start records and terminal records, including auxiliary requests.
API, model and transport failures are separate from implementation quality.
Input/output, cache and reasoning fields retain provider-reported values;
unreported fields stay null. `usage_complete` means complete input/output
accounting and call inventory, not known values for all optional breakdowns.
Gateway session identity and native OpenCode session IDs are labelled separately.

`usage/context-evidence.json` maps the first request to the original prompt and
source blocks. OpenCode's numbered Read rendering is matched line by line, with
message/string indices and first/last line recorded. The terminal newline is
explicitly unobservable in that rendering. Truncated or changed content fails.
Source discovery is recorded separately from prompt delivery; neither proves
model understanding or a causal intervention effect.

`telemetry/monitor.db` is dedicated to one Run. Gateway-derived OTLP passes through
`ingest-raw`; raw DB readback and `normalize-raw` validate Run ID, request count
and input/output counts. Linking twice skips the append-only import to avoid
doubled usage. This is gateway observation, not native OpenCode telemetry support.

```powershell
python -m outer.harness.cli preserve --run MS1-001-explained-001 --archive artifacts/archive --include evidence
python -m outer.harness.cli verify-package --archive artifacts/archive --package run-MS1-001-explained-001 --sha256 <receipt-hash>
python -m outer.harness.cli restore --archive artifacts/archive --package run-MS1-001-explained-001 --sha256 <receipt-hash> --destination runs/restored/MS1-001-explained-001
python -m outer.harness.cli --runs-dir runs/restored rescore --run MS1-001-explained-001
python -m outer.harness.cli --runs-dir runs/restored aggregate
```

Use the emitted package reference or `archive-reference.json`. Restoration
refuses changed files and incompatible existing destinations. The recorded
evaluator image must remain locally available: the package includes evaluator
bytes and image digest, **not an exported Docker image**. For another machine,
also retain pinned images with Docker `image save`/`image load`. Restore, rescore
and aggregate never call a model. Schema 2 packages include native state,
gateway originals, scoring work databases, results and monitor readback. Keep
raw data in ignored `runs/` or `artifacts/`, outside public Git.

## Validate and accept

```powershell
python -m unittest discover -s outer/tests -p 'test_*.py'
dotnet run --project inner/evaluator/MusicStore.Evaluator.Tests -c Release
pwsh -NoProfile -File inner/calibration/run-calibration.ps1
python outer/verify/verify.py --repo .
python outer/verify/probe-agent.py --intervention preload
python outer/verify/probe-containers.py
python -m outer.harness.cli acceptance --task MS1-001
```

The first six commands use no real model and keep separate attempt directories.
The container probe runs the production controller with a local mock upstream,
and exercises completion, timeout, operator stop, crashed-controller recovery,
HTTP failure, missing usage, wrong model and a truncated response. Its synthetic
credential is never the Windows user credential. Original logs, manifests and
per-case expectations are retained under a unique `_container-probe-*` directory.
`acceptance` uses the real model for three arms twice, saving a plan first. A
harness failure stops the batch for repair. A quality failure may remain a valid
observation. Acceptance also requires at least one full application pass and a
restore/rescore without model execution. Container isolation/stop, real usage,
all six Runs and generated application workflows must pass before delivery.

MS1-001 evaluates 29 published requirements at version 1.1.0. XML/HTML parsing
corrections preserve this meaning and change the evaluator build identity.
Authentication, administration, deployment, general security and performance
are out of scope. Persistence checks the published `Orders.OrderId` row contract,
not all order details or `Order.Total`. Publish and version broader criteria
before collecting new Runs. See the [task template](../outer/templates/task/README.md)
for adding another task. Additional task validation and statistical claims are
outside this delivery.
