"""Offline pair-admission decision only; never dispatch, buy, delete or set N.

The user confirmed on 2026-09-22 that paid overage is disabled. Monetary limits,
two-Run dollar reservations and reset horizons are not admission conditions.
API unavailability pauses acquisition; recovery does not replace failed slots.
Storage forecasts are not bounds. This check is not wired to a launcher.
"""
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

from research.catalog_allocation_review import read, write_new


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('UTC timestamp is missing')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() != timedelta(0):
        raise ValueError('UTC timestamp required')
    return result


def decide(record, now=None):
    now = now or datetime.now(timezone.utc)
    reasons = []
    # Usage percentages/reset times are optional operational context, not dollar
    # reservations. An outstanding API failure is cleared only after recovery
    # and dispatch reconciliation, never just because a reset timestamp passed.
    if record.get('api_recovery_pending') is True:
        reasons.append('api_recovery_pending')
    storage = record.get('storage', {})
    # Each physical-space forecast must have an inspectable basis. No reserve is
    # silently counted as freed by uploading; these are not worst-case bounds.
    if storage.get('basis_verified') is not True or not storage.get('evidence_sha256'):
        reasons.append('storage_reservation_basis_unverified')
    components = ('next_pair_retained_bytes', 'generation_scratch_bytes', 'sqlite_finalize_bytes',
                  'public_copy_bytes', 'archive_bytes', 'download_bytes', 'restore_bytes')
    try:
        sizes = [storage[key] for key in components]
        if any(type(n) is not int or n < 0 for n in sizes) or type(storage['free_bytes']) is not int:
            raise ValueError('Invalid byte count')
        required = sum(sizes)  # one pair staged at a time; no discretionary reserve
        if storage['free_bytes'] < required:
            reasons.append('insufficient_local_physical_space')
        disk_age = (now - timestamp(storage['checked_at_utc'])).total_seconds()
        if not 0 <= disk_age <= 300:
            reasons.append('disk_readback_not_within_5_minutes')
    except (KeyError, ValueError, TypeError):
        required = None
        reasons.append('storage_component_unknown')
    operational = not reasons
    if record.get('fixed_execution_plan_verified') is not True:
        reasons.append('execution_plan_not_fixed')
    if record.get('experiment_start_authorized') is not True:
        reasons.append('experiment_start_not_authorized')
    return {'kind': 'offline_pair_admission_not_dispatch', 'checked_at_utc': now.isoformat(),
        'planning_admission_pass': operational, 'may_start_pair': not reasons,
        'blocking_reasons': reasons, 'required_additional_local_bytes': required,
        'monetary_gate_applied': False,
        'quota_policy': 'user_confirmed_no_paid_overage_pause_on_unavailability',
        'launcher_integration': 'not_implemented', 'model_called': False,
        'new_allocation_created': False, 'account_rotated': False,
        'completion_guaranteed': False, 'spending_cap_introduced': False,
        'reservation_risk': 'Pilot-based demand can be exceeded. Pause on quota/storage failure, preserve partial and uncertain slots, never replace or switch models.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--record', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    saved = read(a.record)
    result = decide(saved.get('record', saved))
    write_new(a.out, result)
    if not result['may_start_pair']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
