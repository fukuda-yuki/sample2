"""Install the fixed catalog contract; no model or evaluator is used in preparation."""
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from . import util

METHOD = 'catalog-return'


def prepare(repo, source):
    base = Path(repo) / 'artifacts/catalog-preparation' / uuid.uuid4().hex
    base.mkdir(parents=True)
    script = Path(repo) / 'research/catalog_return_contract.py'
    original = Path(source) / 'MvcMusicStore-Completed/MvcMusicStore/Models/SampleData.cs'
    started = time.monotonic()
    result = subprocess.run([sys.executable, str(script), 'prepare', '--source', str(original),
                             '--out', str(base / 'derived')], capture_output=True)
    (base / 'stdout.log').write_bytes(result.stdout)
    (base / 'stderr.log').write_bytes(result.stderr)
    util.write_new_json(base / 'preparation.json', {'exit_code': result.returncode,
        'duration_seconds': time.monotonic() - started, 'model_called': False,
        'source_sha256': util.sha256_file(original), 'extractor_sha256': util.sha256_file(script)})
    if result.returncode:
        raise ValueError('Catalog preparation failed; retained at ' + str(base))
    (base / 'tools').mkdir()
    shutil.copyfile(script, base / 'tools/catalog_return_contract.py')
    return {'catalog-derived': base / 'derived', 'catalog-tools': base / 'tools'}


# Run inside the actual worker, before OpenCode, under the same user and mounts.
# Its evidence goes to researcher-owned state, never into the model's prompt.
WORKER_PREFLIGHT = r'''
import hashlib, json, os, subprocess, sys
from pathlib import Path
def sha(b): return hashlib.sha256(b).hexdigest()
base = Path('/inputs/catalog-derived')
manifest = json.loads((base/'manifest.json').read_bytes())
common = json.loads((base/'common.json').read_bytes())
paths = [Path(common['source']), Path('/inputs/catalog-tools/catalog_return_contract.py')]
paths += [base/name for name in manifest['files']]
files = {}
for path in paths:
    raw = path.read_bytes()
    try:
        fd = os.open(path, os.O_WRONLY)
    except OSError:
        readonly = True
    else:
        os.close(fd)
        readonly = False
    files[str(path)] = {'sha256':sha(raw), 'bytes':len(raw), 'readable':True, 'readonly':readonly,
                        'mode':oct(path.stat().st_mode & 0o777)}
assert all(x['readonly'] for x in files.values())
assert files[common['source']]['sha256'] == common['source_sha256']
assert files[str(paths[1])]['sha256'] == manifest['extractor_sha256']
for name, expected in manifest['files'].items():
    assert files[str(base/name)]['sha256'] == expected['sha256']
retrievals = []
for offset, limit in [(1,80), (361,71)]:
    args = ['python3', str(paths[1]), 'read-source', '--source', common['source'],
            '--offset', str(offset), '--limit', str(limit)]
    value = subprocess.run(args, capture_output=True, check=True).stdout
    dest = Path('/state')/('catalog-range-%s-%s.txt' % (offset,limit))
    dest.write_bytes(value)
    retrievals.append({'offset':offset,'limit':limit,'sha256':sha(value),'bytes':len(value),
                      'evidence_file':dest.name})
Path('/state/catalog-access.json').write_text(json.dumps({'verified':True,'files':files,
    'retrievals':retrievals, 'actor':'harness_preflight', 'model_retrieval':False}, indent=2))
prompt = open('/inputs/prompt.txt', 'rb')
os.dup2(prompt.fileno(), 0)
os.execvp('opencode', ['opencode','run','--pure','--format','json','--title','MS1-001',
                     '--model',sys.argv[1]])
'''
