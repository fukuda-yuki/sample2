# Continuity study: one allocated pair

This is a selected public slice of one assigned pair in the frozen two-family
source-information study, or an explicitly labeled technical sharing fixture.
Both arms, failures, partial usage and unassessed outcomes remain included.
Music Store and ContosoUniversity are two distinct source families; the two
semantic variants within each family are not independent applications.
`STUDY.json` retains the plan, assignments, source commit and original local
bundle hash. A research bundle contains 128 assignments. A technical fixture
is separately labeled and does not count toward research acquisition.
This slice is not the complete research corpus or proof of quality maintenance.

`MANIFEST.json` lists original and public hashes, exclusions and transformations.
Local home paths are replaced only as explicitly recorded. Request/response
bytes, gateway databases and saved evaluation evidence remain byte-identical
unless their manifest entries say otherwise. Private oracle files, evaluator
binaries, native agent state, evaluation databases and most legacy inputs are
excluded. Original private Runs are retained. This distribution supports saved
evidence extraction, not a full model/evaluator replay or independent oracle
acceptance. The task uses synthetic operational data and an executed .NET
compatibility reference; it is not a receipt for running the legacy Framework app.

Verify downloaded sizes and hashes against `pair.manifest.json` before restoring
into a new directory with a trusted checkout:

```powershell
python -B -m research.catalog_share restore --root pair.zip --asset-manifest pair.manifest.json --out restored-pair
```

From `restored-pair`, extract saved evidence without a model or evaluator:

```powershell
python -B -m research.catalog_share extract --root . --out ../extracted-requests.json
```

The reader verifies public file hashes, saved SQL/OTLP identities and complete
reported totals when present. Missing or inconsistent usage stays unknown;
saved responses and DONE do not establish complete totals. Offline extraction
does not rescore a product, reparse SSE or mark human review passed. The delivery
workflow runs the downloaded reader with sockets blocked, compares extraction
hashes, then removes only its owned public/transfer copies before allowing the
next pair. Retained finalization receipts permit cleanup recovery without another
model dispatch. See the bundled notices, upstream attribution and license texts.
