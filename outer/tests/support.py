"""Shared fixtures for the outer harness tests. No model is involved."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import util  # noqa: E402

TASK_ID = 'TEST-001'
CONDITION_ID = 'C01'
RUN_ID = 'TEST-001-C01-001'


def condition(spec_sha256):
    return {
        'schema_version': 1,
        'condition_id': CONDITION_ID,
        'task_id': TASK_ID,
        'task_title': 'テスト用の条件',
        'start_state': {'kind': 'legacy-source', 'source_repository': 'example/legacy',
                        'source_branch': 'main', 'source_commit': '0' * 40,
                        'license_note': 'テスト用'},
        'environment': {'runtime': 'dotnet', 'sdk': 'test', 'network': 'none'},
        'migration_request': 'テスト用の移行要求',
        'input_policy': {'allowlist': ['legacy-source'], 'denied': ['inner/', 'docs/']},
        'budget': {'kind': 'wall_clock_seconds', 'value': 120, 'scope': 'run'},
        'agent': {'agent_id': None, 'model_id': None, 'agent_version': None,
                  'tool_versions': None, 'subagent_policy': None},
        'evaluation': {'evaluation_version': '1.0.0',
                       'spec_path': 'inner/spec/requirements.json',
                       'catalog_path': 'inner/spec/catalog.json',
                       'spec_sha256': spec_sha256,
                       'evaluator_sha256': None,
                       'evaluator_build': {'source_path': None, 'source_commit': None,
                                           'assembly': None, 'command': None,
                                           'sdk_version': None, 'sha256_origin': None}},
    }


def pin_evaluator(run_dir, sha256, origin=None, command=None):
    """Set (or clear) the evaluator build pinned by the run's condition copy.

    Pinning a hash also pins where it came from, so the condition carries the
    provenance the outer requires.
    """
    path = Path(run_dir) / 'condition.json'
    data = util.read_json(path)
    entry = data['evaluation']
    entry['evaluator_sha256'] = sha256
    entry['evaluator_build'] = {
        'source_path': 'inner/evaluator/MusicStore.Evaluator' if sha256 else None,
        'source_commit': 'test' if sha256 else None,
        'assembly': 'inner/evaluator/MusicStore.Evaluator/bin/Release/net8.0/MusicStore.Evaluator.dll' if sha256 else None,
        'command': (command or 'dotnet build inner/evaluator/MusicStore.Evaluator/MusicStore.Evaluator.csproj -c Release') if sha256 else None,
        'sdk_version': 'test' if sha256 else None,
        'sha256_origin': (origin or 'test fixture') if sha256 else None}
    util.write_json_atomic(path, data)
    return path


def make_repo(root, spec_sha256=None):
    repo = Path(root) / 'repo'
    (repo / 'outer' / 'conditions' / TASK_ID).mkdir(parents=True)
    (repo / 'inner' / 'spec').mkdir(parents=True)
    (repo / 'docs').mkdir(parents=True)
    write_text(repo / 'inner' / 'spec' / 'requirements.json',
               json.dumps({'specVersion': 'stub', 'taskId': TASK_ID,
                           'taskTitle': 'テスト用の台帳', 'requirements': []}, indent=2) + '\n')
    write_text(repo / 'inner' / 'spec' / 'catalog.json', '{"stub": true}\n')
    actual = util.sha256_file(repo / 'inner' / 'spec' / 'requirements.json')
    util.write_new_json(repo / 'outer' / 'conditions' / TASK_ID / 'condition.json',
                        condition(spec_sha256 or actual))
    return repo


def fill_agent(repo, task_id=TASK_ID):
    """Fill the agent fields so a non-synthetic start is allowed."""
    path = Path(repo) / 'outer' / 'conditions' / task_id / 'condition.json'
    data = util.read_json(path)
    data['agent'] = {'agent_id': 'test-agent', 'model_id': 'test-model',
                     'agent_version': '0', 'tool_versions': {'test': '0'},
                     'subagent_policy': 'none'}
    util.write_json_atomic(path, data)
    return data['agent']


def make_legacy(root):
    legacy = Path(root) / 'legacy'
    (legacy / 'Controllers').mkdir(parents=True)
    write_text(legacy / 'readme.txt', 'dummy legacy input\n')
    write_text(legacy / 'Controllers' / 'StoreController.cs', '// dummy\n')
    return legacy


def make_seed(root):
    seed = Path(root) / 'seed'
    web = seed / 'MusicStore.Web'
    (web / 'Views' / 'Home').mkdir(parents=True)
    write_text(web / 'MusicStore.Web.csproj', '<Project Sdk="Microsoft.NET.Sdk.Web">\n</Project>\n')
    write_text(web / 'Program.cs', '// seed\n')
    write_text(web / 'Views' / 'Home' / 'Index.cshtml', 'seed\n')
    return seed


def make_env(root):
    """Return (repo, runs_dir, legacy, seed) for one test."""
    root = Path(root)
    repo = make_repo(root)
    return repo, root / 'runs', make_legacy(root), make_seed(root)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_text(path, text):
    """Write LF bytes. Path.write_text would turn '\\n' into CRLF on Windows."""
    Path(path).write_bytes(text.encode('utf-8'))
