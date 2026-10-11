"""Private, hash-bound technical acceptance resources in the same global budget.

This is accounting only: no adopted slots, retry reservations or authorization
are inherited. The actual origin and closed Run inventory must be supplied.
"""
from datetime import datetime, timezone
from pathlib import Path
from outer.harness import util
from research import live_pilot


def read(reference):
    from research.acquisition_pipeline import usage_for_manifests
    receipt=util.read_json(live_pilot.checked(reference))
    if set(receipt)!={'kind','started_at','runs'} or receipt['kind']!='technical_acceptance_resources_v1' or not receipt['runs']:
        raise ValueError('Explicit technical resource origin and Run inventory required')
    origin=datetime.fromisoformat(receipt['started_at'])
    if origin.tzinfo is None or origin>datetime.now(timezone.utc):raise ValueError('Invalid shared resource clock origin')
    paths=[];identities=set()
    for row in receipt['runs']:
        if set(row)!={'manifest','raw_usage'}:raise ValueError('Explicit sealed technical Run evidence required')
        path=live_pilot.checked(row['manifest']);manifest=util.read_json(path)
        identity=manifest['run_instance_id']
        if (path.name!='manifest.json' or identity in identities
                or manifest.get('stop_confirmed') is not True
                or (manifest.get('network_cleanup') or {}).get('confirmed') is not True
                or not manifest.get('ended_at') or not manifest.get('started_at')
                or datetime.fromisoformat(manifest['started_at'])<origin
                or row['raw_usage']!=util.tree_hashes(path.parent/'usage/raw')):
            raise ValueError('Technical Run changed, duplicated, unstopped or outside shared clock')
        identities.add(identity);paths.append(path)
    return receipt['started_at'],usage_for_manifests(paths)
