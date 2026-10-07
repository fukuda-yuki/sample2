# Bounded resource observation retry

Wave08 (slots 12/13) stopped at 2026-10-07 15:36 UTC after both
independent observers recorded `TimeoutExpired` in sample 74, at 4.42/4.46
seconds. Prior samples reported healthy resources. The frozen collector has a
four-second subprocess timeout inside its ten-second overall deadline. Its
saved error does not identify which subprocess timed out; an exact command
cause is not established.

The controller now permits one fresh observation after `TimeoutExpired` or
`probe_timeout`, using only the time remaining within the original ten-second
budget. Identity errors and resource failures are not retried. A second failure,
an exhausted deadline, or a late successful response remains unhealthy. The
first failed sample is retained in `retry_evidence` in the persisted observation;
missing observations are never replaced with previous counters. The fixed
collector/monitor, cadence (10 seconds), and staleness limit (30 seconds) are
unchanged. Research assignments, evaluation, usage, and provider settings are
unchanged.

Validation: 135 resource-supervisor, recovery, transition, and campaign tests
passed. New cases cover fresh recovery inside the budget, repeated timeout,
ownership-error rejection, exhausted budget, and late-result rejection. Actual
sampling under the successor remains the operational validation.

Wave08 originals and STOP history remain intact. The existing owner completes
saved-artifact recovery; only its parent driver is detached during successor
preparation to prevent a competing wave. No low-quality result is discarded.
