# Cancelled request recovery

The retained pair 10 preload run reached the fixed 1800-second limit. Its final
transmitted request has `usage: null` and `usage_complete: false`. Recovery used
to raise AttributeError instead of retaining this missingness.

Recovery now preserves observed tokens as a lower bound and keeps unknown
request identities separately. A cancelled request is not reclassified as a
provider failure and does not authorize a quality-based replacement.

The driver can select unattempted slots while an earlier slot is held. Existing
wave closure, owned-resource release, per-slot retry eligibility and campaign
STOP admission checks still apply. Held slots are not counted as accepted and
remain visible when all other initial slots have been attempted.

The acquisition checkout and original attempts remain unchanged. Use the
separately committed recovery controller provenance when recovering an older
campaign, then carry the retained decisions and cumulative usage into the next
successor before acquisition continues.
