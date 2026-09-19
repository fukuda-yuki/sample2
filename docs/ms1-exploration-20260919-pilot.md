# Six-Run exploratory pilot, before new acquisition

Population: the six direct Runs in `runs/acceptance-64ad09cd85ca`. All 322 provider calls and 532 native tool actions reconcile. Provider input/output, identities and saved original hashes agree; no evaluation or model was rerun. All six original artifacts scored 29/29 under evaluation 1.2.0.

| Run | Calls | Input | Output | Mean input | Multi-tool requests | First build call | Largest input increase |
|---|---:|---:|---:|---:|---:|---:|---|
| MS1-001-explained-001 | 45 | 3,342,070 | 40,441 | 74268.2 | 17 | 24 | call 6: +29,059 |
| MS1-001-explained-002 | 71 | 4,380,332 | 38,941 | 61694.8 | 0 | 53 | call 5: +15,192 |
| MS1-001-explore-001 | 62 | 4,048,388 | 57,180 | 65296.6 | 21 | 34 | call 9: +14,707 |
| MS1-001-explore-002 | 52 | 3,160,186 | 43,466 | 60772.8 | 14 | 27 | call 4: +18,896 |
| MS1-001-preload-001 | 38 | 2,526,844 | 46,186 | 66495.9 | 18 | 12 | call 3: +15,700 |
| MS1-001-preload-002 | 54 | 4,096,295 | 52,945 | 75857.3 | 17 | 32 | call 34: +18,667 |

## What the retained process shows

- The first transmitted input is 8,028 tokens for explore, 15,578 for preload, and 8,167 for explained. Each exact initial prompt remains observable in every call; every injected block remains in every call of its Run. Later input differences also contain generated code, tool results and intervening actions.
- explore-001/002: the largest input increases follow early SampleData.cs acquisition. It remains visible in 54/49 later requests. Totals differ with both request count (62/52) and mean input; source discovery alone does not explain every later call.
- preload-001: 38 calls with 71 tool actions; early seed-source output remains in 36 later requests. No unchanged-range re-read was established by the conservative range classifier. Its low total is associated with fewer model calls despite the larger initial input.
- preload-002: 54 calls with 85 actions. Four identical source ranges are read again (shared layout, home view and two view models). The largest input jump, +18,667 at call 34, follows a 51,295-character application-start/log output at call 33, retained across 21 later requests. The seed source is also retained across 51 later requests. These are observed correspondences, not assigned token savings.
- explained-001: two 53,025/53,013-character SampleData.cs reads from different source locations occur at call 5; each persists in 40 later requests. The next input grows by 29,059 tokens. The duplicate paths are distinct inputs; semantic duplication requires inspecting content, not only names.
- explained-002: no request issues multiple tools; 70 tool actions require 71 model calls, compared with 92 actions/45 calls in explained-001. Its average input is lower, but cumulative input is higher. The largest increase follows the large shell-based model-source read. A two-message hash-variant change occurs at call 4; the original prompt remains present, so this is not evidence of wholesale context removal.
- No native build action displayed a compiler/MSBuild/NuGet error signature. Textual test-failure flags and revisions are available in the action table; neither is the evaluator quality verdict. Unknown shell processing remains visible rather than being assigned an invented purpose.

## Hypotheses frozen before acquisition

H1: initial delivery versus later acquisition; H2: large tool-output retention; H3: action grouping and repeated validation/revision. Predictions, counterexamples, fixed metrics and stopping rules are in `ms1-exploration-20260919-protocol.md`. The new batch retains all current inputs and does not implement any suggested intervention.

## Reproduction and boundaries

Run `python -m research.analyze --runs-dir runs/acceptance-64ad09cd85ca --cohort existing6 --out <new-output-directory>` from the repository root. The frozen result is `artifacts/exploration/20260919/pilot-v1/analysis.json`; CSV companions expose calls, actions, observed read ranges and Run summaries. Audit and source-hash receipts are alongside it.

Action labels overlap; sum neither label counts nor per-action tokens. Character exposure is not token attribution. Shell path/line recovery is conservative and has explicit indeterminate cases. These two Runs per arm support hypotheses, not causal or generalizable treatment conclusions.
