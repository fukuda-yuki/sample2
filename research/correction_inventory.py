"""Freeze the 25 expected attempts from acquisition plans and archive references.

This builder never reads analysis.json. Its inventory is an explicit audit input.
"""
import argparse
import json
from pathlib import Path
from outer.harness import preserve
from research.validate import digest, read


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2); f.write('\n')


def build(repo):
    repo = Path(repo).resolve()
    pilot = Path('runs/acceptance-64ad09cd85ca')
    new = Path('runs/exploration-20260919-ms1')
    old_analysis = Path('artifacts/exploration/20260919')
    anchors = [pilot/'acceptance-plan.json', pilot/'acceptance-result.json', new/'frozen-plan.json',
        new/'batch-journal.jsonl', new/'batch-result.json', new/'resume-v1/resumed-plan.json',
        new/'resume-v1/result.json', new/'resume-v1/prior-journal.jsonl']
    pp, pr = read(repo/pilot/'acceptance-plan.json'), read(repo/pilot/'acceptance-result.json')
    nr, np = read(repo/new/'resume-v1/result.json'), read(repo/new/'frozen-plan.json')
    planned = [{'run_id': f"MS1-001-{r['intervention']}-{r['attempt']:03d}", 'cohort': 'pilot'} for r in pp['cases']]
    pilot_rows = {r['run_id']: r['row'] for r in pr['runs']}
    new_rows = {r['case']['run_id']: r for r in nr['results']}
    initial = np['slots']
    supplementary = [r['case'] for r in nr['results'] if r['case'].get('replacement_for')]
    if len(planned) != 6 or len(initial) != 18 or len(supplementary) != 1 or not nr['complete']:
        raise ValueError('Unexpected frozen acquisition inventory')
    result = {'schema_version': 2, 'groups': {}, 'runs': [], 'anchors': {},
        'basis': 'frozen acquisition plans, dispatched result rows and verified immutable packages'}
    all_hashes = {}
    for group, batch, cases, rows, analysis_name in [
            ('pilot', pilot, planned, pilot_rows, 'pilot-v1.0.1'),
            ('new', new, initial + supplementary, new_rows, 'new-resumed-v1')]:
        receipt = old_analysis/analysis_name/'source-hashes.json'
        result['groups'][group] = {'source_hashes': receipt.as_posix(), 'source_hashes_sha256': digest(repo/receipt)}
        for case in cases:
            rid = case['run_id']; root = repo/batch/rid
            manifest = read(root/'manifest.json')
            reference = read(root/'archive-reference.json')
            row = rows[rid] if group == 'pilot' else rows[rid]['row']
            recorded_reference = row['archive'] if group == 'pilot' else rows[rid]['archive']
            if row['run_instance_id'] != manifest['run_instance_id'] or recorded_reference != reference:
                raise ValueError('Acquisition/archive binding mismatch: ' + rid)
            package = preserve.verify(repo/batch/'_archive', reference['package_id'], reference['sha256'])
            payload = repo/batch/'_archive/packages'/reference['package_id']/'payload'
            if digest(payload/'manifest.json') != digest(root/'manifest.json'):
                raise ValueError('Archived manifest differs: ' + rid)
            entry = {'group': group, 'cohort': 'pilot' if group == 'pilot' else 'supplement' if case.get('replacement_for') else 'primary18',
                'run_id': rid, 'run_instance_id': manifest['run_instance_id'], 'root': (batch/rid).as_posix(),
                'manifest_sha256': digest(root/'manifest.json'), 'archive': (batch/'_archive').as_posix(),
                'package': reference, 'package_files': len(package['files']), 'allowed_audit_issues': []}
            if manifest['run_instance_id'] == 'bc54629544d141d687318f51ae44e9d7':
                entry['allowed_audit_issues'] = ['missing:usage/raw/started.jsonl', 'missing:usage/raw/events.jsonl',
                    'missing:evidence/agent.jsonl', 'native_session_count:0']
            result['runs'].append(entry)
            for name, info in preserve.tree(root).items():
                all_hashes[(batch/rid/name).as_posix()] = info['sha256']
            print('Inventoried ' + group + '/' + rid, flush=True)
    result['anchors'] = {p.as_posix(): digest(repo/p) for p in anchors}
    return result, all_hashes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, default=Path.cwd())
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.out.exists(): raise SystemExit('Refusing to overwrite correction inventory')
    inventory, originals = build(a.repo)
    write_new(a.out/'originals-all-hashes.json', originals)
    inventory['all_originals_receipt_sha256'] = digest(a.out/'originals-all-hashes.json')
    write_new(a.out/'inventory.json', inventory)
    print(json.dumps({'runs': len(inventory['runs']), 'all_original_files': len(originals), 'out': str(a.out)}))


if __name__ == '__main__':
    main()
