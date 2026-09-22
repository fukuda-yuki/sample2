# One allocated MS1 catalog pair

`MANIFEST.json` identifies both allocated slots, the complete frozen plan, every
original file, public hashes, transformations, exclusions and missing Run
directories. Selection follows slot order. Failed and incomplete Runs remain
included; missing evidence is never zero usage. `acquisition-journal.jsonl`
distinguishes dispatch, result, pause and recovery. Read the full plan for the
fixed denominator; one pair is not the complete study.

Download every asset in the part manifest. Verify the full archive and each
part hash against the Release receipt. The trusted repository's
`research.catalog_delivery` restores multipart archives, then the bundled
standard-library reader extracts saved requests without a model or evaluator:

```powershell
python -B -m research.catalog_share extract --root restored-pair --out extraction.json
```

The frozen analysis source and dependency specification are included. Scientific
analysis still needs all allocated pairs, preserved missingness and the bound
launch receipt. A successful extraction is not a new quality evaluation.

The plan and frozen analysis source are included byte-for-byte, preserving their
hashes after relocation. Per-pair saved observations, the launch receipt and the
minimal no-model baseline inputs are included when present. The documented
exclusions still apply; unavailable observations remain explicitly unknown.

See `THIRD-PARTY-NOTICES.md` and `LICENSES/`. Native state/auth caches, evaluation
DB/WALs, runtime binaries, duplicate workspaces and most upstream legacy files
remain excluded under the explicit bounded sharing contract. This prevents full
native-state inspection, evaluation-DB query replay and self-contained environment
reconstruction. Original private copies remain retained. This distribution does
not create a new project-wide reuse license.

Every future pair requires a review of the exact public bytes, embedded images,
new dependencies and notices before upload. Existing notices are starting
attribution, not advance approval of material generated in later Runs.
