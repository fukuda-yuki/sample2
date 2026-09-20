"""Read-only impact audit of an existing browser batch; never observe again."""
import argparse
from collections import Counter
from pathlib import Path

from outer.harness import browser_cart, util


def audit(root, batch, out):
    root, batch, out = map(lambda p: Path(p).resolve(), (root, batch, out))
    if out.exists():
        raise FileExistsError(out)
    before = util.tree_hashes(batch)
    summary = util.read_json(batch/'summary.json')
    cases, failures, verdicts, preservation = [], [], Counter(), []
    for row in summary['rows']:
        if not row.get('evidence'):
            continue
        result = root/row['evidence']
        output = util.read_json(result/'evaluation.json')
        baseline = util.read_json(root/row['baseline']/'evaluation.json')
        receipt = util.read_json(result/'browser-cart/receipt.json')
        intent = util.read_json(result/'browser-intent.json')
        cleanup = util.read_json(result/'browser-cleanup.json')
        assert browser_cart.stored_coverage_complete(result, row['run_instance_id'], row['artifact_sha256'], row['spec_sha256'])
        assert output['verdict'] == row['verdict'] and output['quality'] == row['quality']
        assert output['baselineEvaluationSha256'] == util.sha256_file(root/row['baseline']/'evaluation.json')
        assert output['baselineResultsSha256'] == util.sha256_file(root/row['baseline']/'results.jsonl')
        verdicts[output['verdict']] += 1
        original = util.read_json(result.parent/'preservation-before.json')
        frozen = util.tree_hashes(root/row['root']/'frozen')
        preserved = original['frozen'] == frozen and all(util.sha256_file(root/p) == h for p, h in original['files'].items())
        assert preserved
        preservation.append({'instance': row['run_instance_id'], 'fixed_files': len(frozen), 'unchanged': preserved})
        for r in baseline['requirements']:
            if r['judgement'] == 'fail':
                failures.append({'instance': row['run_instance_id'], 'run': row['run_id'], 'requirement': r['id'],
                                 'baseline': row['baseline'], 'sha256': output['baselineEvaluationSha256']})
        for removal in receipt['removals']:
            page = util.read_json(result/'browser-cart'/removal['before']['path'])['page']
            expected = 2 if removal['checkId'] == 'C-015' else 1
            valid = (len(page['rows']) == 1 and page['rows'][0]['count'] == str(expected)
                     and page['rows'][0]['album'].rstrip('/') == '/Store/Details/1'
                     and page['totals'] == [f'{8.99 * expected:.2f}'])
            events = util.read_json(result/'browser-cart'/(removal['checkId'] + '-events.json'))
            clicks = sum(e['kind'] == 'ui-click-remove' for e in events)
            cases.append({'instance': row['run_instance_id'], 'check': removal['checkId'],
                          'action': removal['action'], 'click_events': clicks, 'start_valid': valid,
                          'cleanup_confirmed': cleanup.get('container_removed') is True and cleanup.get('network_removed') is True,
                          'receipt_sha256': util.sha256_file(result/'browser-cart/receipt.json'),
                          'cleanup_sha256': util.sha256_file(result/'browser-cleanup.json'),
                          'owned_container': intent['launch_command'][intent['launch_command'].index('--name') + 1]})
    affected = [c for c in cases if c['action'] != 'click-remove' or c['click_events'] != 1
                or not c['start_valid'] or not c['cleanup_confirmed']]
    assert before == util.tree_hashes(batch)
    report = {'batch': str(batch), 'batch_files': before, 'cases': cases, 'affected': affected,
              'quality_verdicts': dict(verdicts), 'baseline_failures': failures, 'preservation': preservation,
              'batch_unchanged': True, 'model_called': False, 'browser_rerun': False,
              'affected_rejudgement_required': bool(affected), 'all_artifact_rerun_required': False}
    out.parent.mkdir(parents=True, exist_ok=True)
    util.write_new_json(out, report)
    return {'cases': len(cases), 'affected': len(affected), 'quality_verdicts': dict(verdicts),
            'baseline_failures': failures, 'fixed_files': sum(p['fixed_files'] for p in preservation)}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', default='.')
    p.add_argument('--batch', required=True)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    print(audit(a.root, a.batch, a.out))
