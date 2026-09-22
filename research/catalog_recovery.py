"""Validate bounded recovery additions without replacing an original Run seal."""
import hashlib
import json
from pathlib import Path
import re

from outer.harness import evaluate, util
from research.catalog_allocation_review import read
from research.catalog_share import inventory, native, safe_member


def appended_rows(root, name, before):
    """Prove the old JSONL bytes are an unchanged prefix, including its newline."""
    raw = native(root / name).read_bytes()
    old = before.get(name, {'bytes': 0, 'sha256': hashlib.sha256(b'').hexdigest()})
    prefix, tail = raw[:old['bytes']], raw[old['bytes']:]
    if (len(prefix) != old['bytes'] or hashlib.sha256(prefix).hexdigest() != old['sha256']
            or prefix and not prefix.endswith(b'\n') or not tail or not tail.endswith(b'\n')):
        raise ValueError('Preserved result index is not an append-only extension: ' + name)
    return [json.loads(line) for line in tail.decode('utf-8').splitlines()]


def validate(root, before, operations):
    """Only named cleanup receipts or newly indexed evaluation attempts may change.

    This verifies evidence after an independently authorized operation; it never
    performs cleanup, scoring or model dispatch. Every old file stays immutable
    except for byte-prefix-verified indexes. Accepted deltas are journaled outside
    the Run so that subsequent recovery also protects the new evidence.
    """
    root = Path(root)
    after = inventory(root) if root.exists() else {}
    added = set(after) - set(before)
    changed = {n for n in before if after.get(n) != before[n]}
    allowed_additions, allowed_indexes = set(), set()
    if set(before) - set(after):
        raise ValueError('Preserved result file was removed during recovery')
    evaluation_rows = None
    requested_evaluations = []
    for op in operations:
        directory = op.get('directory', '')
        parts = safe_member(directory).parts
        if len(parts) != 2 or parts[0] != 'evaluations':
            raise ValueError('Recovery directory must identify one evaluation attempt')
        if op.get('kind') == 'browser_cleanup':
            resources_name = directory + '/browser-resources.json'
            if resources_name not in before:
                raise ValueError('Cleanup must reference a preserved resource owner')
            owner = read(native(root / resources_name))
            prefix = directory + '/browser-cleanup-attempts/'
            index = prefix + 'index.jsonl'
            rows = appended_rows(root, index, before)
            results = {}
            for name in sorted(added):
                if not name.startswith(prefix) or name == index:
                    continue
                suffix = name[len(prefix):]
                match = re.fullmatch(r'([0-9a-f]{32})-(result|[1-9][0-9]*-intent)\.json', suffix)
                if not match:
                    raise ValueError('Unexpected cleanup evidence file')
                item = read(native(root / name))
                if item.get('owner') != owner['owner']:
                    raise ValueError('Cleanup evidence has another owner')
                if match[2] == 'result':
                    if (item.get('run_instance_id') != owner['run_instance_id']
                            or item.get('model_called') is not False or item.get('browser_observed') is not False):
                        raise ValueError('Cleanup result identity or operation differs')
                    results[match[1]] = item
                else:
                    # An interrupted earlier cleanup can leave only an intent.
                    # Keep it, provided it names the same preserved resource.
                    if not any(item.get('kind') == r['kind'] and item.get('name') == r['name']
                               for r in owner['resources']):
                        raise ValueError('Cleanup intent has another resource')
                allowed_additions.add(name)
            if (len(rows) != len(results) or any(item not in rows for item in results.values())
                    or rows[-1].get('confirmed') is not True or rows[-1].get('status') != 'complete'):
                raise ValueError('Cleanup index must match completed recovery receipts')
            lock = directory + '/controller.lock'
            if lock in added:
                if native(root / lock).read_bytes() != b'0':
                    raise ValueError('Unexpected cleanup lock contents')
                allowed_additions.add(lock)
            allowed_indexes.add(index)
        elif op.get('kind') == 'evaluation':
            sequence = op.get('sequence')
            if type(sequence) is not int or sequence < 1 or not op.get('authorization_reference'):
                raise ValueError('Evaluation recovery needs its sequence and separate authorization reference')
            if evaluation_rows is None:
                evaluation_rows = appended_rows(root, 'evaluations/index.jsonl', before)
            rows = [r for r in evaluation_rows if r.get('sequence') == sequence and r.get('directory') == directory]
            if len(rows) != 1 or sequence in requested_evaluations:
                raise ValueError('Evaluation recovery must match one new index entry')
            row = rows[0]
            work = f'evaluation-work/{sequence:03d}/'
            logs = {f'evidence/scoring-{sequence:03d}-{stream}.log' for stream in ('stdout', 'stderr')}
            if any(n.startswith((directory + '/', work)) or n in logs for n in before):
                raise ValueError('Recovery cannot reuse an existing evaluation directory or sequence')
            old_rows = native(root / 'evaluations/index.jsonl').read_bytes()[:before.get('evaluations/index.jsonl', {}).get('bytes', 0)]
            if any(r.get('sequence') == sequence for r in (json.loads(line) for line in old_rows.splitlines())):
                raise ValueError('Recovery cannot reuse an indexed evaluation sequence')
            condition = read(native(root / 'condition.json'))['evaluation']
            artifact = read(native(root / 'snapshot.json'))['artifact_sha256']
            record = read(native(root / directory / 'record.json'))
            if (row.get('run_id') != root.name or row.get('evaluation_version') != condition['evaluation_version']
                    or row.get('spec_sha256') != condition['spec_sha256']
                    or row.get('evaluator_sha256') != condition['evaluator_sha256']
                    or row.get('artifact_sha256_outer') != artifact
                    or util.artifact_hash(native(root / 'frozen')) != artifact
                    or any(record.get(k) != v for k, v in row.items())):
                raise ValueError('Recovery evaluation must retain the fixed artifact and evaluation conditions')
            allowed_additions.update(n for n in added if n.startswith((directory + '/', work)) or n in logs)
            allowed_indexes.add('evaluations/index.jsonl')
            requested_evaluations.append(sequence)
        else:
            raise ValueError('Unsupported recovery operation')
    if evaluation_rows is not None:
        if len(evaluation_rows) != len(requested_evaluations) or len(evaluate.used_sequences(native(root))) > 3:
            raise ValueError('Evaluation recovery exceeds the fixed two-rescore limit or has undeclared attempts')
    if changed - allowed_indexes or added - allowed_additions - allowed_indexes:
        raise ValueError('Preserved result changed outside declared recovery operations')
    return {'operations': operations, 'changes': {name: {'before': before.get(name), 'after': after[name],
        **({'appended_byte_range': [before.get(name, {}).get('bytes', 0), after[name]['bytes']]}
           if name in allowed_indexes else {})} for name in sorted(added | changed)}}


def replay(before, deltas):
    """Reconstruct the protected inventory from append-only journal deltas."""
    result = dict(before)
    for delta in deltas:
        for name, change in delta['changes'].items():
            if result.get(name) != change['before']:
                raise ValueError('Recovery history no longer matches the preserved seal')
            result[name] = change['after']
    return result
