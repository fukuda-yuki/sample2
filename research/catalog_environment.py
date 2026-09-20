"""Pin the researcher-side browser dependencies before any pilot dispatch."""
import json
from pathlib import Path
import shutil
import subprocess

from outer.harness import util
from outer.harness.security import child_environment

KEYS = {'NODE_PATH', 'SAMPLE2_BROWSER_EXECUTABLE'}


def capture(probe_file, repo):
    probe_file = Path(probe_file).resolve()
    probe = util.read_json(probe_file)
    env = probe['environment']
    if not probe.get('verified') or set(env) != KEYS:
        raise ValueError('A verified existing browser-environment probe is required')
    node = shutil.which('node')
    if not node:
        raise ValueError('Node is unavailable')
    # Use the exact sanitized environment that the ordinary run CLI will receive.
    script = "console.log(JSON.stringify({node:process.version,playwright:require('playwright/package.json').version}))"
    result = subprocess.run([node, '-e', script], env=child_environment(env),
                            capture_output=True, text=True, timeout=30, check=True)
    actual = json.loads(result.stdout)
    if any(actual[k] != probe[k] for k in ('node', 'playwright')):
        raise ValueError('Browser probe versions differ from the execution environment')
    record = {'environment': env, 'node_path': node, 'node_sha256': util.sha256_file(node),
        'browser_sha256': probe['browser_sha256'],
        'dependency_hashes': {name: util.tree_hashes(Path(env['NODE_PATH']) / name)
                              for name in ('playwright', 'playwright-core')},
        'collector_sha256': util.sha256_file(Path(repo) / 'inner/browser/cart-review.cjs'),
        'probe_file': str(probe_file), 'probe_sha256': util.sha256_file(probe_file)}
    validate(record, repo)
    return record


def validate(record, repo):
    env = record['environment']
    if set(env) != KEYS:
        raise ValueError('Only browser dependency paths may be forwarded')
    if (shutil.which('node') != record['node_path']
            or util.sha256_file(record['node_path']) != record['node_sha256']
            or util.sha256_file(env['SAMPLE2_BROWSER_EXECUTABLE']) != record['browser_sha256']):
        raise ValueError('Pinned Node or browser changed')
    if util.sha256_file(Path(repo) / 'inner/browser/cart-review.cjs') != record['collector_sha256']:
        raise ValueError('Browser collector changed')
    for name, files in record['dependency_hashes'].items():
        if not files or util.tree_hashes(Path(env['NODE_PATH']) / name) != files:
            raise ValueError('Pinned browser module changed: ' + name)
    if util.sha256_file(record['probe_file']) != record['probe_sha256']:
        raise ValueError('Browser probe changed')
    return env
