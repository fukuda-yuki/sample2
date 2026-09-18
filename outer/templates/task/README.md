# Add a task

This template is outside the preset inventory. Replace every placeholder and
calibrate the evaluator before running it.

1. Copy `task.json` into `outer/profiles/tasks/<task_id>.json`. Pin a full source
   commit and verify its license. The worker receives its archive, without `.git`,
   private evaluation assets or previous Runs.
2. Write the public request using `public-request.md`, then put its final text in
   `migration_request`. Publish every interface and persistence rule used by the
   evaluator. Use the same request for all interventions.
3. Add a ledger and any catalog under `inner/spec/<task_id>/`. Record the exact
   ledger SHA-256 in `evaluation.spec_sha256`. Version judgment meaning separately
   from the evaluator assembly hash.
4. Add a .NET evaluator project under `inner/evaluator/` and specify its project
   path and assembly. Follow the contract below. This runtime prepares .NET 8
   with SQLite; other dependencies require an image update and validation.
5. Register positive, independently valid, defective and evaluator-fault fixtures
   in a task-specific calibration driver. Use `calibration-plan.json`: freeze
   exact verdict, failed/blocked sets, exit code and missingness before execution.
   Every attempt must have a new output directory.
6. Pick fixed relevant source paths for preload and write a source-grounded
   explanation. Do not include a solution or hidden scoring data. Verify actual
   initial-input rendering and truncation with the selected CLI.
7. Run calibration, isolation tests and a live pilot. A new JSON profile alone
   does not establish acceptance of a new task.

## Evaluator contract

```text
dotnet <assembly> --artifact /artifact --out /result --work /work
  --spec /assets/requirements.json --catalog /assets/catalog.json
  --evaluation-version <version> --sequence <positive integer>
```

`/artifact` and `/assets` are read-only; `/work` is empty per invocation. Build
and execute a copy, store mutable databases under `/work`, record lifecycle and
stop descendants. Never read previous scoring state or call a model. Compile
and functional failures are task results; evaluator/runtime faults are separate.

Emit `evaluation.json` containing `taskId`, `specSha256`, `artifactSha256`,
`artifactPath` (`/artifact`), `evaluationVersion`, unique `evaluationId`, `verdict`,
nullable `quality`, `requirementCount`, `passedCount`, `failedCount`, `blockedCount`
and per-requirement evidence. Emit `evaluator-manifest.json` with
`evaluatorSha256`. Keep HTTP, database and process evidence alongside results.
Use the artifact hash algorithm in `outer/harness/util.py`. Exit 0 for a valid
quality judgment, including failed submissions; exit 2 for an evaluator fault
with null quality. The outer harness checks identity and retains the result; it
does not define the task's correctness criteria.
