# Executed independent education migration family (#22)

The added family is `contoso-enrollment`, task variants `CU1-ENR-C` and `CU1-ENR-D`.
It is materially separate from the Music Store upstream and business domain.
Two variants count as **one** education family, making two selected families in
the v2 candidate register. Unobtained data-entry/scheduling ideas contribute zero.
Selection and development/reserved-family membership were fixed before any model
outcomes. Music Store is development/calibration. Education is reserved for future
model outcomes, while its reference/oracle/evaluator calibration and basic human
review are exposed. It is not a secret held-out benchmark. The old one-family plan
and its receipts remain historical artifacts; the coordinator owns the new plan.

## Real source and controlled installation

Upstream: [jbogard/ContosoUniversity](https://github.com/jbogard/ContosoUniversity/tree/5c4e4ec11395172f82606f95ec520f0a93508541),
exact commit `5c4e4ec11395172f82606f95ec520f0a93508541`, Apache-2.0 LICENSE.
`research/tasks/contoso-enrollment/source-pin.json` pins 21 exact files by Git blob
SHA1 and SHA256. This is the declared Student/Course/Enrollment subset, not a full
legacy application checkout. The original Framework application is **not_run**;
the .NET 8 compatibility reference is executed. Upstream and successor examples
are public; known-solution contamination has not been eliminated.

Synthetic raw SQLite uses old singular `Person/Department/Course/Enrollment` and
TPH `Discriminator=Student`. The required target converts to plural tables and
maps `Person.FirstName` to `Students.FirstMidName`. Source `Person.FullName` is
`LastName + ", " + FirstMidName`. IDs101/202, department10/20, courses1045/2021/4041,
enrollments9001/9002/9003/9010, field values and relationships are retained. Original
department budgets/date fields and externally assigned course IDs are meaningful.

Stored grades0/1/3 have source enum semantics. C has `A,B,C,D,F`, yielding A/B/D;
D's explicit researcher installation overlay has `B,A,D,C,F`, yielding B/A/C.
Enrollment9003 is null/`No grade` in both. Credits are C4/3/2 and D5/1/2; these are
raw retained data, not hardcoded public answers. The single public request gives
neither grade mapping. Modified source files carry an overlay notice; LICENSE is
retained. Both installations are synthetic, not claimed deployed customer data.

Create/edit/search and readonly course/enrollment details form the finite workflow.
Missing/blank/oversize names, invalid dates and unknown IDs have explicit safe
behavior. Login, instructors, administration, grade editing/deletion, sorting,
pagination, concurrency/performance and external integrations are excluded.

## Reproduction and ordinary scoring interface

Run from the integrated repository after A's evaluator/spec and C's hooks merge:

```powershell
python -m research.fetch_education_source
python -m research.education_tasks prepare
python -m research.education_tasks reference --variant C --out artifacts/education-review-build-C
python -m research.education_tasks reference --variant D --out artifacts/education-review-build-D
```

The fetch command uses only public exact-commit HTTPS URLs, no credentials or
persistent access configuration. Existing source is read and fully verified.
Alternatively use `prepare --source-root <pinned-copy>` to read a previously
obtained snapshot. Incomplete/mismatching old outputs are retained and rejected;
choose a new namespace rather than overwrite history.

The B-owned adapter `outer/harness/migration_input.py` retains `migration-v1` and
routes by strict task identity. It returns only source and original raw business
directories. Private target derivative, catalog and oracle never enter model
inputs or preload context. Public requests are exact-byte-identical within C/D;
context paths and read access are the same. The runtime profile/condition changes
are coordinator/C-owned. `ConnectionStrings__SchoolContext` specifies the target.
The reference imports raw old data when that target path is absent. Its optional
Data content permits normal frozen collection, which excludes SQLite: in that
case import reads `/inputs/existing-business/legacy-school.sqlite`.

Each task profile selects `education-1.0.0`,
`Education.Evaluator/Education.Evaluator.csproj`, `Education.Evaluator.dll`, private
assets, and `migration_contract.import_input=legacy-school.sqlite`. C mounts only
that original raw file for fresh-path scoring. A owns the twelve normative
requirements, production evaluator, browser and ordinary score calibration.

## Finite evidence and limits

B output `artifacts/education-acceptance-v1/workflow-integrated-contract/summary.json`: C52/52,
D52/52 passed; fixed-C decoder on D fails exactly grade9001/9002/9010, while its
49 other checks pass. Three publish builds succeeded. Tests include fresh schema
conversion, source/raw-data interpretation, every retained field/relationship,
nullable grades, joins, create/edit/new ID, nine invalid create and nine invalid
edit cases, unknown IDs, search, restart and no old-row mutations. The independent
Python oracle parses old source and raw SQLite and checks manually asserted labels;
it does not ask the reference for expectations. Five education controls plus four
Music Store controls passed. Initial launcher-relative-path failure and prior
receipts are retained. No model was dispatched.

After ordinary A/C calibration, final integrated code must still pass its necessary
checks. B reference acceptance alone is not full Issue22/research readiness. Old
Framework execution remains not_run, human oracle/workflow confirmation remains
not_run, and broad legacy equivalence/general migration quality is not inferred.
`education_review.py` creates exact source/data/public/spec/code/evidence hash maps
and seven concrete pending human checks. The signed human judgment must be separate;
automated/AI results cannot mark it passed.

Human preview uses copied published applications and separate databases:

```powershell
& .\research\Start-EducationReview.ps1 -PublishedRoot '<B-worktree>\artifacts\education-acceptance-v1' -OutputDirectory '<B-worktree>\artifacts\education-human-review-v1'
# Default C http://127.0.0.1:5055, D http://127.0.0.1:5056
& .\research\Stop-MigrationReview.ps1 -ReviewDirectory '<B-worktree>\artifacts\education-human-review-v1'
```

The launcher hides app windows, strips unrelated/credential environment variables,
and records PID/generation/path/binary/raw-input hashes. The shared stop helper
checks exact owned process paths/generations. Existing Music Store review URLs5051
and5052 are separate. Starting apps does not complete human confirmation.
