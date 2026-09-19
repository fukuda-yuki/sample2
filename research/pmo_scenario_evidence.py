"""Evidence-only helpers for the delegated MS1 review; never run a model/evaluator.

Browser interactions are recorded separately through Codex Browser Use. SQLite
reads run inside the live container in a read-only transaction, including WAL.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone


REPO = Path(__file__).resolve().parents[1]
MATERIAL = Path('artifacts/exploration/20260919/human-review-resumed-v1')
IMAGE = 'sha256:a0bd46f3cebfc2502fe930cb50827379180b7c3f4f297d5a9e2f7201f38d5c3d'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Evidence is append-only: do not silently replace an earlier attempt.
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(path):
    return {p.relative_to(path).as_posix(): sha(p)
            for p in sorted(path.rglob('*')) if p.is_file()}


def aggregate(files):
    ordered = sorted(files, key=lambda p: p.replace('/', '\\').encode('utf-16-be'))
    return hashlib.sha256(''.join(f'{p} {files[p]}\n' for p in ordered).encode()).hexdigest()


def docker(*args):
    result = subprocess.run(['docker', *args], capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout


def prepare(out):
    relocated = REPO / 'work/relocated-ms1-correction-v3'
    receipt = read(relocated / MATERIAL / 'review-targets.json')
    assert receipt == read(REPO / MATERIAL / 'review-targets.json')
    baseline, targets = {}, []
    for number, target in enumerate(receipt['targets']):
        condition, run_id = target['condition'], target['run_id']
        original = REPO / 'runs/exploration-20260919-ms1' / run_id
        run_copy = relocated / original.relative_to(REPO)
        manifest, snapshot = read(original / 'manifest.json'), read(original / 'snapshot.json')
        assert manifest['run_instance_id'] == target['run_instance_id']
        assert read(run_copy / 'manifest.json')['run_instance_id'] == target['run_instance_id']
        frozen = inventory(original / 'frozen')
        assert frozen == {k: v['sha256'] for k, v in snapshot['frozen'].items()}
        assert inventory(run_copy / 'frozen') == frozen
        assert aggregate(frozen) == snapshot['artifact_sha256']
        app = relocated / MATERIAL / condition / 'application'
        app_files = inventory(app)
        expected = {str(Path(f['destination']).relative_to(Path(target['application']))).replace('\\', '/'): f['sha256']
                    for f in receipt['files'] if f['condition'] == condition}
        assert app_files == expected == inventory(original / 'evaluation-work/001/publish')
        assert app_files == inventory(REPO / MATERIAL / condition / 'application')
        evaluation_dir = next(p for p in (original / 'evaluations').iterdir() if p.is_dir())
        record = read(evaluation_dir / 'record.json')
        assert record['artifact_sha256_outer'] == snapshot['artifact_sha256']
        assert record['spec_sha256'] == sha(original / 'evaluation-assets/requirements.json')
        baseline[run_id] = {'original': inventory(original), 'v3_frozen': frozen,
                            'v3_application': app_files, 'prepared_application': app_files}
        targets.append({**target, 'application': str(app), 'artifact_sha256': snapshot['artifact_sha256'],
                        'application_tree_sha256': aggregate(app_files), 'application_files': len(app_files),
                        'evaluation_id': record['evaluation_id'], 'spec_sha256': record['spec_sha256'],
                        'image': IMAGE, 'container': f'ms1-pmo-{out.name}-{condition}',
                        'port': 18401 + number, 'state': str(out / condition / 'state')})
    save(out / 'integrity-before.json', baseline)
    save(out / 'targets.json', targets)
    save(out / 'prepare.json', {'at': datetime.now(timezone.utc).isoformat(), 'pass': True,
                              'image': json.loads(docker('image', 'inspect', IMAGE)),
                              'review_targets_sha256': sha(relocated / MATERIAL / 'review-targets.json')})
    print(json.dumps(targets, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'start', 'restart', 'snapshot', 'stop', 'verify'])
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--condition', choices=['explore', 'preload', 'explained'])
    parser.add_argument('--label', default='observation')
    args = parser.parse_args()
    out = args.out.resolve()
    if args.action == 'prepare':
        prepare(out)
        return
    targets = read(out / 'targets.json')
    if args.action == 'verify':
        before = read(out / 'integrity-before.json')
        results = []
        for target in targets:
            run_id, condition = target['run_id'], target['condition']
            areas = {'original': REPO / 'runs/exploration-20260919-ms1' / run_id,
                     'v3_frozen': REPO / 'work/relocated-ms1-correction-v3/runs/exploration-20260919-ms1' / run_id / 'frozen',
                     'v3_application': Path(target['application']),
                     'prepared_application': REPO / MATERIAL / condition / 'application'}
            for name, path in areas.items():
                current = inventory(path)
                expected = before[run_id][name]
                changes = [p for p in sorted(current.keys() | expected.keys()) if current.get(p) != expected.get(p)]
                results.append({'run_id': run_id, 'area': name, 'files': len(current), 'changed': changes, 'pass': not changes})
        save(out / f'integrity-{args.label}.json', results)
        assert all(r['pass'] for r in results)
        print(json.dumps(results))
        return
    target = next(t for t in targets if t['condition'] == args.condition)
    folder = out / args.condition
    name = target['container']
    if args.action == 'start':
        state = Path(target['state'])
        state.mkdir(parents=True, exist_ok=False)
        keys = folder / 'keys'
        keys.mkdir()
        command = ['run', '-d', '--name', name, '--label', f'sample2.pmo.review={out.name}',
                   '--label', f'sample2.review.instance={target["run_instance_id"]}',
                   '--network', 'bridge', '--publish', f'127.0.0.1:{target["port"]}:8080',
                   '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                   '--tmpfs', '/tmp:rw,size=128m',
                   '--mount', f'type=bind,source={target["application"]},target=/app,readonly',
                   '--mount', f'type=bind,source={state},target=/data',
                   '--mount', f'type=bind,source={keys},target=/root/.aspnet/DataProtection-Keys',
                   '--workdir', '/app', '--env', 'ASPNETCORE_ENVIRONMENT=Production',
                   '--env', 'ConnectionStrings__MusicStoreEntities=Data Source=/data/store.sqlite',
                   '--env', 'Logging__LogLevel__Microsoft.AspNetCore=Information',
                   IMAGE, 'dotnet', target['entry_assembly'], '--urls', 'http://0.0.0.0:8080']
        save(folder / 'launch.json', {'at': datetime.now(timezone.utc).isoformat(), 'command': ['docker', *command]})
        print(docker(*command))
    else:
        details = json.loads(docker('inspect', name))[0]
        assert details['Config']['Labels']['sample2.pmo.review'] == out.name
        assert details['Config']['Labels']['sample2.review.instance'] == target['run_instance_id']
        if args.action == 'snapshot':
            code = """import json, sqlite3
c=sqlite3.connect('file:/data/store.sqlite?mode=ro',uri=True)
c.row_factory=sqlite3.Row
c.execute('PRAGMA query_only=ON')
c.execute('BEGIN')
tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
result={'journal_mode':c.execute('PRAGMA journal_mode').fetchone()[0], 'tables':{}}
for t in tables:
    result['tables'][t]=[dict(r) for r in c.execute('SELECT * FROM "'+t.replace('"','""')+'"')]
print(json.dumps(result))
c.rollback()
c.close()
"""
            data = json.loads(docker('exec', name, 'python3', '-c', code))
            save(folder / f'{args.label}.db.json', {'at': datetime.now(timezone.utc).isoformat(), **data})
            print(json.dumps({'tables': {t: len(rows) for t, rows in data['tables'].items()},
                              'orders': data['tables'].get('Orders')}))
        elif args.action in ('restart', 'stop'):
            print(docker(args.action, name))
        save(folder / f'{args.label}.{args.action}.container.json', json.loads(docker('inspect', name)))
    with (folder / f'{args.label}.{args.action}.server.log').open('x', encoding='utf-8') as stream:
        subprocess.run(['docker', 'logs', '--timestamps', name], stdout=stream, stderr=stream, check=True)


if __name__ == '__main__':
    main()
