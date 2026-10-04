# Finite evaluator diagnosis checks

Run with .NET 8 or later:

```powershell
dotnet run --project inner/evaluator/Education.Evaluator.DiagnosticsChecks --configuration Release
```

This console check program calls the actual evaluator's methods using reflection.
It creates a synthetic SQLite database, HTTP baseline, and hash-verified browser
receipt in its own temporary directory. It never launches an app, browser,
worker, Docker container, or model, and never reads or rescores historical Runs.
The synthetic screenshot files are placeholder bytes, not browser evidence.

When NuGet is unavailable, a Windows x64 check can compile the same evaluator
source files against an existing read-only directory of the frozen dependency
DLLs (AngleSharp, Microsoft.Data.Sqlite, and SQLitePCLRaw). Supply that directory
with `--property:OfflineReferenceDirectory=ABSOLUTE_DIRECTORY`; the check does
not load the old Education.Evaluator.dll. An empty local restore source may be
supplied with `--property:RestoreSources=EMPTY_DIRECTORY` to avoid network use.
Set process-local TEMP/TMP to a writable directory if required by the sandbox.

The 14 assertions cover actual unique-ID discovery despite a midnight date
suffix; exact date comparison failure and success; unambiguous identification;
the actual browser composition predicate; preserved HTTP failures and blocked
checks; browser coverage independent of unrelated HTTP coverage; unchanged
whole-evaluation completion, critical verdict and null quality; explicit
implementation revision; observer faults and an unobserved browser action.

The frozen criteria version remains `education-1.0.0`. Implementation revision
`education-1.0.0-diagnostics-1` is emitted separately. The normal evaluator
project and all criteria ledgers/oracles/prompts stay unchanged. For deployment,
build the evaluator separately at the recorded clean source commit and pin the
actual assembly hash in new phase-specific assets. Do not replace any historical
Run's frozen evaluator assets or evaluation outputs.
