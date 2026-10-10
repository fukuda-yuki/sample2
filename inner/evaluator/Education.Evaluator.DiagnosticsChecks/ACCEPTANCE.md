# Education 1.1.0 finite acceptance

This is a new evaluator version, not a replacement of the frozen
`education-1.0.0` binary, requirements, results or acquisition inputs. The
implementation revision is `education-1.1.0-observation-1`. Run reassessment
must use a separate evaluation ID and output root bound to the original
artifact, original acquisition identity and this new binary/spec identity.

## Evidence and oracle

The saved `CU1-ENR-D-explore-5073` results report E-003 differences only in two
`Students.EnrollmentDate` and two `Departments.StartDate` cells. Its E-012
receipt has the completed ordinary workflow and stored midnight date text.
The public prompt requires calendar-date values and scopes `yyyy-MM-dd` to
portable UI observation. Date text representation alone therefore must not
be used to infer loss of the calendar value. This is an explicit new-version
comparison policy; it does not relabel the old results in place.

Only `Students.EnrollmentDate` and `Departments.StartDate` use calendar
comparison. Accepted database text is a valid ASCII `yyyy-MM-dd`, optionally
followed by space or `T`, `00:00:00`, and an optional fraction containing only
zeros. The number of zero digits does not change the date value. Nonzero
clock/fraction, timezone/offset, malformed or impossible dates are rejected.
This policy also applies to these fields when validating the raw source
projection. Generic strings, names, nulls, IDs and numeric comparison retain
their separate contracts. UI dates remain exact `yyyy-MM-dd`.

The saved 5080 impossible-date HTTP 302 is a product failure: invalid dates
must redisplay HTTP 200 without mutation. No normalization changes that
expectation. The nine existing invalid cases remain intact.

## Changed observations

- A created student is the unique positive DB ID added to the full pre-create
  ID set, with every pre-create ID retained and no duplicate stored IDs. A
  preexisting matching name is never selected for dependent Edit. An ambiguous
  delta returns no ID, keeping dependent Edit blocked. A Create-form GET that
  changes the database is recorded as a failure before the POST.
- Read-only DB comparisons use an explicit deferred transaction across their
  related reads. Committed WAL rows are valid observations; an uncommitted
  concurrent write is excluded. Missing required table/columns and duplicate
  original identifiers are observed product mismatches. SQLite open, corrupt,
  busy, locked or I/O exceptions propagate as observer faults. SQLite column
  identifier case is respected; returned Student field labels are aliased to
  the canonical observation names without altering stored values.
- Invalid-input and restart snapshots serialize typed, structured cells.
  SQL null, empty text, binary values, row boundaries and column boundaries
  remain distinct. Snapshots still cover the four declared domain tables,
  including their extra columns, rather than claiming all possible tables.
- Duplicate positive UI row identifiers cannot collapse into a passing set.
- Browser schema 2 binds the collector request hash, acquisition instance,
  artifact, spec, version and explicit owned loopback origin. A hash-bound
  HTTP 500–599 from an allowed ordinary Create/Edit operation is a product
  failure, even if a later observer/evidence fault occurs. POST observations
  require a confirmed click and recorded payload. Arbitrary exceptions,
  foreign targets and unbound responses are not product-failure evidence.
  Four mutually consistent captures from another origin are rejected.
- Partial HTTP failure evidence does not establish the full workflow. Any
  observer fault keeps browser coverage partial and quality null; already
  verified product failures remain sticky. Complete coverage additionally
  requires the four bound captures, screenshots, exact UI values and the
  independent read-only DB observation.

## Reproduction

`Program.cs` exercises the actual evaluator's private methods. The offline
build can reference either the current source directly or a separately built
actual `Education.Evaluator.dll`; the acceptance script uses the latter.
Normal NuGet builds remain available when `OfflineReferenceDirectory` is not
set. The repository pins SDK 8.0.425.

```powershell
./inner/evaluator/Education.Evaluator.DiagnosticsChecks/build-offline.ps1 `
  -DependencyDirectory <FROZEN_EVALUATOR_DEPENDENCY_DIRECTORY> `
  -BuildRoot <SEPARATE_PRIVATE_BUILD_ROOT> `
  -ProductReceipt <OPTIONAL_NEW_BROWSER_FIXTURE_RECEIPT>
```

The optional receipt is a newly collected finite fixture, never a modified
historical receipt. It adds an interoperability assertion. The script rebuilds
the standalone evaluator twice at the same compile path, compares DLL/PDB
bytes, runs the checks against that DLL, copies unchanged dependency files
plus the new DLL/PDB into `linux-bundle`, and records source/dependency/file
hashes, SDK and commands in `build-receipt.json`. Invoke the Linux bundle with
`dotnet Education.Evaluator.dll`; a Windows apphost is not packaged. A successful
build does not itself prove Linux application execution.

The accepted local run has **59 finite assertions**, or **60** with the
independently collected real-browser HTTP-500 fixture receipt. Coverage includes
normal/invalid/leap/date-representation cases; new-ID, no-addition, duplicate
and removed-original cases; committed/uncommitted WAL; original value loss;
null versus empty snapshots; missing schema versus corrupt/absent DB faults;
identifier case; exact UI date; failed/blocked baseline preservation;
partial/fault coverage; response identity and sticky-first-failure boundaries.

The initial DB-midnight test failed on the old implementation. Additional
zero-fraction, null/empty snapshot and identifier-case regressions were observed
failing before their respective repairs. This is a finite acceptance suite,
not proof that all previously unexplored product/evaluator behavior is safe.
The default transaction's write-lock behavior was not reproduced as a fault;
explicit `deferred:true` expresses the intended read-only operation. The
[provider source](https://github.com/dotnet/efcore/blob/v8.0.31/src/Microsoft.Data.Sqlite.Core/SqliteTransaction.cs)
documents its transaction branch.

## Remaining scope limits

The suite does not execute model requests, start research acquisition, or
rescore original Runs. Full hosted application checks, collector cleanup,
STOP/lease handling, package restoration, all-200 source/build mappings and
separate saved-artifact reassessment have their own acceptance evidence.
Long-lived busy/locked DBs are handled by propagation, but were not induced as
a distinct timed fixture here. E-002's existing dependency/project/binary
scanner was preserved and has not received a general project-resolution proof
from this suite. Human review remains not run.
