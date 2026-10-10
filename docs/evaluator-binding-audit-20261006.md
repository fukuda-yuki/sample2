# Original 200 Run evaluator binding audit

The read-only audit found no byte/provenance binding mismatch in the original
200 Run cohort. This establishes which preserved inputs and evaluator binaries
were used; it does not approve their requirement semantics or quality verdicts.
The original files, frozen evaluator versions and prior scores were preserved.

| Task | Runs | Requirements/checks per Run | Preserved evaluator |
| --- | ---: | ---: | --- |
| CU1-ENR-C | 50 | 12 / 12 | diagnostics `63efeac8…`: 50 |
| CU1-ENR-D | 50 | 12 / 12 | original `4f36fac6…`: 6; diagnostics `63efeac8…`: 44 |
| MS1-CONT-A | 50 | 31 / 33 | `1feb0576…`: 50 |
| MS1-CONT-B | 50 | 31 / 33 | `1feb0576…`: 50 |

The total is 4,300 requirement instances and 4,500 declared check instances.
There are four pinned private-oracle byte identities, each used by 50 Runs.
The saved scoring index contains 131 scored, 67 incomplete and 2 evaluator-fault
records. These are historical states, unchanged by this audit.

The audit verified the condition against the Run manifest, task/runtime profiles,
prompt and input manifests/files, requirements/spec version and hash, catalog,
private oracle and initial/import databases, each frozen evaluator dependency
against both asset and runtime manifests, and all frozen submission files against
their snapshot and recomputed artifact identity. It also joined index, record,
actual output manifests and result requirement/check IDs. It hashed 28,299
referenced files plus 5,285 frozen files. SQLite files were read only as bytes;
no SQLite connection, evaluator, model, container or original-output writer ran.

The Music final browser-composition manifests inherit their implemented-check
declarations from `http-only/evaluator-manifest.json`. Both stages were checked;
the final manifest alone is insufficient evidence for that declaration.

| Finding | Status and consequence |
| --- | --- |
| Declared identities, hashes, ledger/check inventory and actual saved binaries | Resolved by byte and metadata checks for all 200; zero binding-issue Runs |
| Nonempty, stopped/fixed submission and bound evaluation assets | 183 candidates for a **separate** assessment; not 183 executable or quality-approved applications |
| Empty frozen submissions | 17; all historically incomplete. Do not fabricate a generated application or count a new assessment as a replacement acquisition |
| Final result rows | 180 have the complete declared requirement/check row inventory; 20 have zero rows, including three with nonempty frozen submissions. Retain unknown coverage |
| Historical source/build declaration | Three actual DLL hashes are distinguishable. Saved build-origin DLLs match. Education diagnostic compile-project hash and all five declared second-build files match. Independent source-to-binary rebuilding was not performed |
| Date meaning, WAL consistency, CreatedId, legacy-name discrimination, generated-app HTTP failures, possible false passes/negatives | Unresolved by this binding audit; require explicit oracle decisions and repair acceptance tests |
| Human review | Not performed by this audit |

The 20 zero-result Runs are missing observations, not duplicate rows or declared
check omissions. The 17 empty submissions account for 17 of those; three others
have saved source but no final result rows. A saved output manifest declaring
implemented IDs does not change that observation gap.

Music's original ledger also contains stale descriptive text: JSON pointers
`/requirements/12/basisDetail`, `/requirements/12/checks/0/observation`,
`/requirements/13/checks/0/observation`, `/requirements/15/checks/0/observation`
retain uniform-price examples. Their requirement expectations already refer to
effective prices. Current source computes C-014 as three effective units, C-015
as one effective unit and C-017 as two units of album 1 plus one of album 2.
`/knownLimits/2` and `/knownLimits/3` retain older statements about unobserved
database preservation/order totals, despite the added migration requirements.
These conflicts need corrected text in a new evaluation specification, with
unchanged historical originals. Current source text is not proof that every
historical binary implemented the intended predicate.

The reusable audit is [research/audit_evaluation_bindings.py](../research/audit_evaluation_bindings.py).
Nine synthetic tests cover tampering, missing implementation manifests,
unimplemented IDs, duplicate result rows, unsafe references, unconfirmed stop,
build-byte mismatch, partial coverage and original-file hash/mtime preservation.
They passed with:

```text
python -B -X utf8 -m unittest research.tests.test_audit_evaluation_bindings -v
```

Private receipts are intentionally outside Git in the operator's
`evaluator-repair-evidence-20261006` directory:

* `original200-binding-audit-v1.json`, SHA-256
  `a09113c86f0a80404600a5b660cb57f0e7168132dee201468a25a70ade4156e2`.
* `original200-saved-build-audit-v1.json`, SHA-256
  `804b8e65bd62a0f5a5c7be0a3c9a95641bbee61fa11aa5dd9c0cc2517a39fca3`.

To reproduce the audit locally, use the original private cohort and a new output
path outside it. The CLI refuses to overwrite an existing receipt. These private
receipts and assets are not a public distribution package.

Method: local `research-analysis` and `scientific-critical-thinking` skills,
their upstream appraisal workflow, and the General Standard/Benchmarking
application sections were read. They apply because this is an automated
software-quality measurement and saved-evidence audit. Identity, observation
completeness and construct validity are assessed separately; checklist counts
are not converted into a quality score. Existing reports were already known;
counts and hashes above were recomputed from source records rather than adopted
from those reports. No external service or additional Skill was invoked.
