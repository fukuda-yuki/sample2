"""Offline pair-admission decision only; never dispatch, buy, delete or set N.

Unknown account limits or missing two-Run reservations fail closed. Reference
pilot demand remains a forecast, not a cap or completion guarantee. This check
does not change Run stopping rules and is not wired to a launcher.
"""
import argparse
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from research.catalog_allocation_review import read, write_new

WINDOWS = ('rolling', 'weekly', 'monthly')


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('UTC timestamp is missing')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() != timedelta(0):
        raise ValueError('UTC timestamp required')
    return result


def positive(value):
    if value is None or isinstance(value, bool):
        raise ValueError('Missing numeric value')
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('Invalid numeric value') from exc
    if not result.is_finite() or result <= 0:
        raise ValueError('Positive finite value required')
    return result


def decide(record, now=None):
    now = now or datetime.now(timezone.utc)
    reasons, windows = [], {}
    usage = record.get('account', {})
    try:
        age = (now - timestamp(usage['checked_at_utc'])).total_seconds()
        if not 0 <= age <= 300:
            reasons.append('account_readback_not_within_5_minutes')
    except (KeyError, ValueError, TypeError):
        reasons.append('account_timestamp_invalid')
    if usage.get('http_status') != 200:
        reasons.append('account_readback_unsuccessful')
    limits = record.get('applicable_limits', {})
    if limits.get('verified_from_account') is not True or not limits.get('evidence_sha256'):
        reasons.append('actual_account_limits_unverified')
    if record.get('paid_overage_disabled_verified') is not True:
        reasons.append('paid_overage_setting_unverified')
    if record.get('no_other_account_consumers_verified') is not True:
        reasons.append('account_usage_not_reserved_for_pair')
    pair = record.get('pair_reservation', {})
    try:
        amount = positive(pair.get('quota_usd'))
    except ValueError:
        amount = None
        reasons.append('pair_quota_reservation_unknown')
    if pair.get('basis_verified') is not True or not pair.get('evidence_sha256') or pair.get('runs') != 2:
        reasons.append('two_run_reservation_basis_unverified')
    try:
        duration = float(positive(pair.get('planning_horizon_seconds')))
    except ValueError:
        duration = None
        reasons.append('pair_planning_horizon_unknown')
    for window in WINDOWS:
        try:
            current = usage['usage'][window]
            percent = current['percent']
            if isinstance(percent, bool) or not isinstance(percent, (int, float)) or int(percent) != percent or not 0 <= percent <= 100:
                raise ValueError('Expected floored integer percentage')
            limit = positive(limits.get('usd', {}).get(window))
            # Official API floors usage percentages; 0% is not necessarily zero.
            remaining_lower = limit * max(Decimal(0), Decimal(99) - Decimal(str(percent))) / 100
            windows[window] = {'remaining_usd_lower_bound': str(remaining_lower), 'limit_usd': str(limit), 'used_percent_floor': percent}
            if current['status'] != 'ok' or amount is None or remaining_lower < amount:
                reasons.append(window + '_insufficient_or_unknown')
            reset = timestamp(current['resetsAt'])
            # A reset is a reason to re-read, never an assumed replenishment.
            if duration is None or reset <= now + timedelta(seconds=duration):
                reasons.append(window + '_reset_before_pair_end')
        except (KeyError, ValueError, TypeError, OverflowError):
            reasons.append(window + '_window_or_limit_invalid')
    try:
        valid_until = timestamp(limits['valid_until_utc'])
        if duration is None or valid_until <= now + timedelta(seconds=duration):
            reasons.append('applicable_terms_expire_before_pair_end')
    except (KeyError, ValueError, TypeError):
        reasons.append('applicable_terms_validity_unknown')
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
        'blocking_reasons': reasons, 'windows': windows, 'required_additional_local_bytes': required,
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
