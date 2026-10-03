"""Input adapter for versioned migration tasks; private oracle never enters inputs."""
from pathlib import Path
import sys

from . import util


def prepare(repo, task):
    repo = Path(repo).resolve()
    if task.get('task_input_adapter') != 'migration-v1':
        raise ValueError('Not a migration-v1 task')
    name = task['start_state']['asset_variant']
    if name not in ('A', 'B') or task['task_id'] != 'MS1-CONT-' + name:
        raise ValueError('Migration variant identity mismatch')
    sys.path.insert(0, str(repo))
    try:
        from research.migration_tasks import prepare_assets
        root = prepare_assets(repo, name)
    finally:
        sys.path.pop(0)
    input_root = root / 'inputs'
    inputs = {key: input_root / key for key in ('legacy-source', 'existing-business')}
    if any(not p.is_dir() for p in inputs.values()):
        raise ValueError('Incomplete migration input preparation')
    return inputs


def receipt(inputs):
    path = inputs['legacy-source'].parents[1] / 'preparation.json'
    return {'path': str(path), 'sha256': util.sha256_file(path), **util.read_json(path)}
