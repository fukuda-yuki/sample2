# Changes after acquisition began

The frozen pre-acquisition protocol and extraction v1.0.0 are at Git commit
`5fa49775c24a5462238f2ca6b05aab0f2001e4c1`. The byte-exact dispatched plan is
`runs/exploration-20260919-ms1/frozen-plan.json`. Neither that plan nor the
protocol, profiles, runtime images, controller or evaluator was changed.

- Case review of the historical six Runs was added separately in
  `pilot-case-review.json`. It distinguishes literal error text from actual
  failures and source files with similar names but different insertion order.
  Frozen multi-label and reacquisition classifications remain unchanged.
- Summary/figure/notebook/ledger validation code was completed during and after
  acquisition. The 10,000-character display bin is explicitly post hoc and is
  not a hypothesis acceptance threshold. These programs cannot dispatch Runs.
- After the batch halted at slot 3, extraction v1.0.1 corrected an empty-sum
  presentation defect: a Run with no reported provider usage now has null
  `observed_input_tokens`/`observed_output_tokens`, not zero. Authoritative totals
  already remained null. A measured zero stays zero; a known partial sum remains
  a partial sum. No observed call value, classification, initial hypothesis or
  experimental condition changed. `new-v1` and the corrected `new-v1.0.1` are
  both retained, and the failed attempt is not removed.

The stopped batch must not be resumed with this modified research source; its
driver's frozen hash check intentionally rejects it. Any later acquisition needs
an explicit new protocol/batch decision after the documented environment and
evaluation issues are resolved. No further model dispatch occurred here.

## Explicit retry amendment R1

The subsequent user instruction on 2026-09-19 explicitly authorized retry and
diagnosis/repair of Docker network exhaustion. The paragraph above describes
the earlier stopped delivery, not a prohibition after that new authorization.
See `docs/ms1-exploration-20260919-retry-amendment.md` for the bounded exception.
The original frozen files and closed result remain unchanged. `resume.py` uses
a separately hashed amended plan, appends a new journal segment, finishes the
remaining initial slots in their original order, and retains the pre-model
Docker failure before its separately identified late supplement. The operational
`network_recovery.py` reclaims only verified stopped and preserved Run networks,
outside measured execution. Runtime/controller/evaluator bytes remain fixed.

## Post-acquisition interpretation and delivery

`resumed-case-review.json` adds semantic annotations to each completed resumed
Run. For example, script invocations and diagnostic log reads can retain an
`other_unknown` frozen label while their meaning is documented separately.
The source-range overlap reconstructed for explore-003's shell loop is an
explicit post hoc annotation, not a silent reclassification. Error-looking
text and an actual final requirement failure are kept distinct.

`evidence_review`, `prepare_reviews`, `report` and `completion` were added as
read-only analysis, delivery and verification utilities. The review launcher
uses copied published applications with separate automated/human state and
the existing Docker bridge. Final report figures label a wholly unobserved
attempt as `no usage`, rather than showing it as a measured zero. None of
these reporting changes alter the frozen R1 extraction/acquisition sources,
intervention contents, evaluator, or Run conditions. Human review remains
unperformed; selection and automated preview checks are separate claims.

After the nineteenth dispatch completed, the supplementary SSE originals
exposed `tool_calls: null` chunks. Extraction v1.0.2 accepts these as empty
tool deltas, preserving actual tool calls and final usage. The frozen R1
source remains byte-exact under `resume-v1/frozen-research-source`; no model
was rerun and no provider original was edited. The before/after hashes are
in `parser-fix-v1.0.2.json`. A nullable-delta regression test brings the
research contract checks to nineteen. Previously completed Run tables are
compared with their earlier extraction outputs to detect unintended changes.

Final visual inspection also exposed provider-reported input decreases while
transmitted characters grew and every previous message hash remained present.
The four decreases above 3,000 tokens are a post hoc descriptive view, recorded
with original request/response references; their internal provider cause is
unknown. They are not labeled as agent compaction or a proven token saving.
The evidence index v2 adds these transitions. Display/notebook v2 clarify that
literal SampleData.cs candidate counts miss variable-based shell reads and
separate two overlapping plot labels; observed values are unchanged.
