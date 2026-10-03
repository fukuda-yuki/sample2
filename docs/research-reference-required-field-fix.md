# Limited Music reference correction: REF-MUSIC-EMAIL-LABEL

The AI research-lead review observed a populated FirstName and missing Email being
rejected with the incorrect `The FirstName field is required.` message. The
reference now selects the first actually missing required address field and names
that field. The same nine fields and nonblank predicate remain required; promo,
checkout persistence, public requests, task profiles and prepared assets are unchanged.

Before changing code, the complete original
`artifacts/research-owner-review-20261003/research-lead-receipt.json` was read. All
131 manifest evidence hashes, its plan hash and the four preview assembly hashes
matched. Its SHA256 is
`4ec3c39c51aea03e036516341fb43f942787681318e0d98c19b7240eb98212fa`.
This is an AI reviewer receipt, with `human_review=not_run`. It does not constitute
human confirmation of Framework behavior, restart/import, all invalid inputs or
the full integrated scorer/browser/cleanup chain.

The latest user steering adopted the limited two-family/four-variant, 16 pairs per
variant, 64 pairs/128 Runs serial research design at the AI research-lead level.
The coordinator records that adoption and remaining execution gates separately.
This reference-label correction does not claim Issue21/22 human closure or start
new acquisition. No model was dispatched for this correction.

## Exact version and evidence binding

Pre-fix B commit: `f2d46f572d2315d8eb6b8b2debee6cde62c66ee9`.
Only the reference `Program.cs` required-field selection/message changes.

| Artifact | Before SHA256 | After SHA256 |
|---|---|---|
| Program.cs | `5d9e68a4b5d5bdbcdd73d1fc68e00e186d089b4f932f0be3415159ebe9f62748` | `7709bbaabc310bfa0d56f6495885f101aa30f3d5ea0d19f34711afd178693a52` |
| A MusicStore.Continuity.dll | `8aed3d0346ba138ae1d782385e1f98fbf3e71a817e048bef44290192c4987626` | `5dbc2abc53080bdb9e5d7bd767d4cde5ebccadbb1c0c59c87ac1e269834aed96` |
| B MusicStore.Continuity.dll | `c963da41aa40d2aa13a968a6dcb7e56fb2df969444986f1d97cdb251e6c4273f` | `0581c8f45ba279d05f6d04ad755f4bc9d718b409cad16819a6fde285f81a11f9` |

New references/published binaries and all correction evidence are in the B
worktree `artifacts/task-missing-email-fix-v1/`. The old
`task-acceptance-v2` binaries, old `task-human-review-v1` databases (including the
review's order7002), original reviewer screenshots/DB snapshots and old technical
receipts were retained. `Program.before.cs` preserves the old source. A separate
`owner-review-verification.json` records every original evidence hash;
`preserved-preview-before-switch.json` and `version-receipt.json` bind old and new
versions. Prior full-workflow receipts continue to describe their original code
and binaries; they are not relabeled as current full-chain acceptance.

`targeted/targeted-receipt.json` SHA256:
`0215c3cffce73b023681456d50d2a5db285fa5966fb2b1f6c897e02883b41f2f`.
It records exactly two invalid POST cases per variant: Email blank, and FirstName
blank as the necessary same-message-branch regression. Both return200 with the
correct field, retained supplied values, unchanged cart HTML and unchanged entire
database rows. All eight assertions per variant passed. Saved HTML/transcripts,
database before/after and the one-hunk source diff accompany the receipt. This
limited check does not repeat the old 18/52 workflows or prove every invalid case.

## Updated preview and reproduction

Only the owned old Music A/B processes were stopped with the existing path and
generation checking helper. Updated copies started with separate new SQLite
files in `task-missing-email-fix-v1/review`, at the same localhost URLs5051/5052.
The original reviewer data remains in the old namespace. Education C/D remained
on5055/5056 with the same PIDs, binaries and databases; they were not restarted.

From B worktree, targeted rerun against those disposable Music copies:

```powershell
python -m research.verify_music_required_field --preview-directory artifacts/task-missing-email-fix-v1/review --prior-verification artifacts/task-missing-email-fix-v1/owner-review-verification.json --prior-program artifacts/task-missing-email-fix-v1/Program.before.cs --out artifacts/task-missing-email-fix-v1/targeted-rerun
& .\research\Stop-MigrationReview.ps1 -ReviewDirectory "$PWD\artifacts\task-missing-email-fix-v1\review"
```

Choose a fresh output directory. The helper performs only the stated branch cases,
adding one album to its own synthetic session cart. It cannot mark human review
passed. The prior reviewer verification is mandatory and hash-checked.

The explicit education scope retains **all supplied Department rows and fields**,
including DepartmentID/Name/Budget/StartDate and Course.DepartmentID relationships.
That is already in the common public request, raw import and independent oracle.
Departments are a preserved supporting relation, not a new administration workflow.
