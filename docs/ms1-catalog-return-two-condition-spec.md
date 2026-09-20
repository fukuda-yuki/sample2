# Catalog return range: two-condition input contract

This file fixes the adopted input byte contract. Production installation and the separately authorized four-Run technical pilot are documented in the [pilot report](ms1-catalog-technical-pilot-20260920-report.md). The task, hypothesis and number of conditions remain unchanged. This is a new two-condition comparison, not a comparison with historical `explore`, `preload` or `explained` Runs.

## Question and sole difference

Does omitting a large source excerpt from the initial model context reduce provider-reported total tokens while maintaining requirement compliance, when both conditions receive identical source files, deterministic extraction, extracted data, confirmation information and retrieval capabilities?

| Item | `catalog-expanded` | `catalog-compact` |
|---|---|---|
| Source, extracted catalog and helper files | Identical bytes and read-only paths | Identical bytes and read-only paths |
| Initial common confirmation | `common.json`, 982 UTF-8 bytes | Same bytes |
| Initial source excerpt | Append `raw-first.txt`, 51,393 bytes including its range header | Do not append it |
| Later source retrieval | Same helper, file tools, range limits and output behavior | Same |
| Other instructions and task hints | Same migration request and public contract | Same |

Only the appended source packet differs. Condition names appear in the harness ledger, not in instructions telling the model to be economical, avoid reading, batch tools, implement deletion, or prefer an architecture. Neither condition receives a deletion hint or a corrected implementation.

## Exact preparation and files

The input is the Completed source in repository `chack411/MVC-Music-Store`, commit `2967afb9d69488641df0d154e2ad5827a7820e71`:

```text
/inputs/legacy-source/MvcMusicStore-Completed/MvcMusicStore/Models/SampleData.cs
SHA-256 cab15100c9230e325ae513c7a9d8b09dc90f21cd7b489a54b0fa93cc2e7512ed
```

The Assets tree remains available, identically in both conditions, as part of the same legacy-source snapshot. Its different `SampleData.cs` is not substituted or merged into this catalog.

The executable specification is [catalog_return_contract.py](../research/catalog_return_contract.py). Both installed profiles call this offline extractor. It refuses a different source hash and incomplete extraction. It parses the literal Genre, Artist and Album initializers; resolves names exactly; assigns IDs from one-based initializer position; and retains array insertion order, titles, artwork URLs and decimal price strings. It does not summarize with an LLM, sort records, drop records, or read evaluator fixtures. JSON object keys are sorted for deterministic serialization; array order is unchanged. Output is UTF-8 without BOM, two-space indentation and LF, with one terminal LF. Prices are decimal strings such as `"8.99"`.

Both conditions mount the same bytes at:

```text
/inputs/catalog-derived/catalog.json
/inputs/catalog-derived/common.json
/inputs/catalog-derived/raw-first.txt
/inputs/catalog-tools/catalog_return_contract.py
```

`catalog.json` contains 10 genres, 149 artists and 246 albums; size 58,349 bytes; SHA-256 `1ddd9fcdab422c8b89322c0910e44c6884a939290c717ead38f8ba9ea1f22c39`. Genre/artist IDs and foreign keys are explicit. The common confirmation verifies IDs 1, 2 and 246. It is capped at 2,048 UTF-8 bytes; exceeding the cap is a preparation fault, not silent truncation. Preparation time and process exit are recorded separately; it makes no model calls.

## Injection point and actual input example

Preparation finishes before the first provider request. The existing migration request is followed in the **same initial user message**, once, by:

```text
<unchanged migration request and public contract>

Catalog preparation:
<exact bytes of common.json>
<expanded only: exact bytes of raw-first.txt>
```

This is a declared initial context intervention. It is not a fabricated tool reply, a conditional first-read hook, or a result inserted later after observing model behavior. Both prompts use the same prefix and insertion point. The initial request serializer must deliver this packet without a second truncation step; its byte hashes are checked at the gateway before acquisition. Later compaction and tool limits remain identical between conditions.

The beginning and key contents of the common JSON are:

```json
{
  "albums": 246,
  "artists": 149,
  "catalog": "/inputs/catalog-derived/catalog.json",
  "catalog_sha256": "1ddd9fcdab422c8b89322c0910e44c6884a939290c717ead38f8ba9ea1f22c39",
  "extraction": "complete; insertion order preserved; no sorting or LLM",
  "genre_counts": {"Alternative":5,"Blues":6,"Classical":34,"Disco":3,"Jazz":12,"Latin":35,"Metal":34,"Pop":2,"Reggae":4,"Rock":111},
  "genres": 10,
  "id_checks": {"1":"The Best Of Men At Work","2":"A Copland Celebration, Vol. I","246":"Ao Vivo [IMPORT]"},
  "read_source": "python3 /inputs/catalog-tools/catalog_return_contract.py read-source --source /inputs/legacy-source/MvcMusicStore-Completed/MvcMusicStore/Models/SampleData.cs --offset 361 --limit 71",
  "source": "/inputs/legacy-source/MvcMusicStore-Completed/MvcMusicStore/Models/SampleData.cs",
  "source_sha256": "cab15100c9230e325ae513c7a9d8b09dc90f21cd7b489a54b0fa93cc2e7512ed"
}
```

The display above condenses nested JSON for readability. The executable example fixes the exact indentation/bytes: common SHA-256 `8bb04e0b9de0612e25c757f37a1ae30a2b3cda02bddf0bcbcfa44c15a8fd3cde`.

The source packet requests physical lines 1–360, without line-number prefixes, capped at **51,200 UTF-8 body bytes**. BOM is omitted and line endings are rendered as LF; the source file itself remains byte-identical. Only complete lines are emitted. A one-line `CATALOG_SOURCE` JSON header reports requested/delivered lines, body bytes, source hash, next offset and EOF. The cap excludes this header and the common confirmation. For the fixed source, the packet delivers lines 1–360, body 51,162 bytes, `next_offset=361`, `eof=false`. It is explicitly not the complete 431-line source.

The resulting context suffixes are 982 bytes (compact) and 52,375 bytes (expanded). Expanded suffix SHA-256: `068705dfdc4f7ebc57567d204f69ce2347278d143f022ed96c67ab87ff4ccb7b`. No model tokens are inferred from these byte sizes.

## Identical retrieval route

The helper is available through the existing shell tool in both conditions:

```sh
python3 /inputs/catalog-tools/catalog_return_contract.py read-source --source /inputs/legacy-source/MvcMusicStore-Completed/MvcMusicStore/Models/SampleData.cs --offset 1 --limit 80
python3 /inputs/catalog-tools/catalog_return_contract.py read-source --source /inputs/legacy-source/MvcMusicStore-Completed/MvcMusicStore/Models/SampleData.cs --offset 361 --limit 71
```

Offsets are one-based, limits are 1–360 lines, and the same 51,200-byte body cap and header rules apply. Invalid ranges/hash mismatches produce an explicit failure. Source and extracted catalog remain readable using ordinary file/shell tools too; there is no arm-specific access restriction. Record actual returned bytes, requests, repeated retrieval and retained context. Increased retrieval is an outcome of the intervention, not grounds to exclude a Run. General shell/read tools and their output caps are identical across conditions; the reference helper is not an arm-specific restriction on those tools.

## Quality and token analysis

The adopted historical browser correction is 9/24 artifacts passing, and 5/17 artifacts (5/18 assigned slots) in the new initial cohort. It does not establish superiority from the old 1/6, 2/6 and 2/5 cells, and does not support assuming that both new conditions already meet a sufficient quality floor.

For each assigned trial report requirement-level outcomes, overall pass/fail, observed coverage, evaluator faults, cleanup status, execution state and token completeness separately. A product failure with an unperformed deletion case remains a known failure **and** incomplete coverage. A cleanup failure preserves quality but prevents operational success. Missing evidence, wrong identity and unsupported selectors never create a pass. Technical missingness is not silently relabeled as product failure, and known HTTP/product failures are not removed from the failure tally by later missingness.

Report both passes/assigned trials and passes/artifacts, with artifact-free technical failures and incomplete evaluations explicitly counted. Requirement pass rates include an unknown/blocked count and their fixed denominators. Primary token reporting uses provider `input_tokens + output_tokens` over **all assigned trials**, including failed products, budget stops and technical failures with usage. Unknown usage is null; retain observed partial usage separately. Do not substitute cache/reasoning subtotals or source characters for primary usage. Report usage-format changes and retained bytes as predeclared sensitivity/descriptive fields, without inferring the provider's internal cause.

A compact failure using fewer tokens is not an efficiency improvement. Success-only token summaries are secondary and cannot support the primary conclusion. Report quality and all-trial token distributions together; a quality decrease precludes a positive efficiency claim. If uncertainty cannot rule out a material quality decrease, call the result inconclusive rather than assume equivalence. Do not select a winner or change the task/hypothesis from the historical small cells.

## Separation from a confirmatory experiment

The technical pilot is now accepted and closed. The subsequent
[fixed confirmation design](ms1-catalog-confirmatory-plan.md) supplies the
proposed repetitions, strict relative quality rule and offline analysis. It
does not authorize acquisition or reopen technical/evaluator acceptance.

The byte contract above is fixed and reproduced offline. The user separately authorized a technical pilot of two Runs per condition, using both pair orders and no replacements; its plan and results are linked above. That pilot checks connection and observation, not efficacy or noninferiority. Before a confirmatory acquisition, separately fix sample size, pairing/order, budget, a justified quality noninferiority margin (or a stricter rule), uncertainty/analysis method and technical-stop/supplement policy. Validate identical common files and request serialization for both conditions, then pin the collector/evaluator/runtime builds. No repeated peeking or selective successful-Run replacement is allowed. These launch decisions require a separate experiment instruction; they do not reopen deletion-evaluator acceptance or add human operation/all-artifact passing as gates.

Offline reproduction (no model):

```powershell
python -m research.catalog_return_contract prepare `
  --source artifacts/sources/2967afb9d69488641df0d154e2ad5827a7820e71/MvcMusicStore-Completed/MvcMusicStore/Models/SampleData.cs `
  --out artifacts/catalog-contract-new-copy
```

An existing output directory is refused. Original Runs, uniform-v3, token values, R-029 corrections and representative selection remain unchanged.
