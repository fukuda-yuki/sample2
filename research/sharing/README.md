# MS1 catalog pilot: first-pair sharing rehearsal

This is the first randomized pair of the four-Run technical pilot, selected by
slot order before the sharing review. It contains `catalog-compact-001` and
`catalog-expanded-001`, including the compact Run's original evaluator fault
and its later adopted evaluation. It is not a confirmatory cohort, a complete
research corpus, a new model execution, or a new evaluation.

The evidence includes both sealed gateway SQLite databases and OTLP, provider
request JSON and response SSE, normalized usage, native agent events and tool
operations, prompts and derived catalog inputs, frozen generated source, every
saved evaluation attempt, HTTP/browser logs, PNGs and browser trace ZIPs. The
complete original pilot plan is supplied so that the two omitted slots remain
visible; do not treat the selected pair as the full four-Run pilot.

`MANIFEST.json` records every selected Run's original file path, size and hash,
each included public file's original and public hash, transformations, and each
excluded file with its reason. Absolute home paths in text and trace ZIP text
members are replaced by `<LOCAL_HOME>`. Transformed originals cannot be recovered
from this public copy. The gateway databases, request bodies, response streams
and frozen products remain byte-identical unless explicitly marked otherwise.

Runtime binaries, package caches, native auth/state databases, evaluation DBs
and their WALs, duplicate workspaces/archives, and most upstream legacy input
files are deliberately omitted from this small rehearsal. Their absence limits
native-state inspection, independent evaluation-DB queries, and exact offline
model/evaluator replay. Original code/assets remain referenced by upstream
commit `2967afb9d69488641df0d154e2ad5827a7820e71` in
`chack411/MVC-Music-Store`; no claim is made that this distribution alone rebuilds
the original environment. Original private copies were not modified or deleted.

## Verify, restore and extract without running a model or evaluator

Download `catalog-pilot-first-pair.zip` and its `.manifest.json` asset. Verify
their hashes against the repository's release receipt. Use the repository reader
or a trusted checkout of the sharing change to restore into an absent directory:

```powershell
python -B -m research.catalog_share restore --root catalog-pilot-first-pair.zip --asset-manifest catalog-pilot-first-pair.manifest.json --out restored-pair
```

Then change into `restored-pair` and use the bundled reader with Python 3.12+;
the real rehearsal used Python 3.14.4. No third-party Python packages, network,
agent, Docker container, browser or evaluator process is required:

```powershell
python -B -m research.catalog_share extract --root . --out ../extracted-requests.json
```

The extractor checks public file hashes, SQLite integrity, exact gateway OTLP,
Run identities and token totals, and retains the recorded evaluation attempts.
It does not reparse SSE, score products, fill missing token values or change
saved judgments. SQLite SQL is in `research/sql/catalog_otel_requests.sql`.
Compare normalized usage and the saved SQL projection rather than treating
individual present spans as proof of complete Run usage. `human_review` remains
`not_run`. See `THIRD-PARTY-NOTICES.md` before reusing or redistributing material.
