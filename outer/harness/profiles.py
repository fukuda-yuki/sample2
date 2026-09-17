"""Task, intervention and runtime profiles; immutable, portable Run inputs."""
import copy
import fnmatch
import json
import re
import shutil
from pathlib import Path

from . import run, util


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', value):
        raise ValueError('Invalid profile identifier')
    return value


def read(repo, kind, name):
    path = Path(repo) / 'outer' / 'profiles' / kind / (identifier(name) + '.json')
    return util.read_json(path)


def inventory(repo):
    return {kind: [util.read_json(p) for p in sorted(
        (Path(repo) / 'outer' / 'profiles' / kind).glob('*.json'))]
        for kind in ('tasks', 'interventions', 'runtimes')}


def resolve(repo, task_id, intervention_id, runtime_id='deepseek'):
    task = read(repo, 'tasks', task_id)
    intervention = read(repo, 'interventions', intervention_id)
    runtime = read(repo, 'runtimes', runtime_id)
    if task['task_id'] != task_id or intervention['id'] != intervention_id or runtime['id'] != runtime_id:
        raise ValueError('Profile identity mismatch')
    if intervention['method'] not in ('explore', 'preload', 'explained'):
        raise ValueError('Unsupported intervention method')
    if (runtime['model_id'] != 'deepseek-v4.1-flash'
            or runtime['endpoint'] != 'https://opencode.ai/zen/go/v1/chat/completions'
            or runtime['concurrency'] != 1 or runtime['subagents'] is not False
            or type(runtime['timeout_seconds']) is not int or runtime['timeout_seconds'] <= 0):
        raise ValueError('Runtime violates the fixed provider, model or execution contract')
    condition = copy.deepcopy(task)
    condition.update(schema_version=2, condition_id=intervention_id,
                     intervention=intervention, runtime=runtime,
                     agent={'agent_id': 'opencode', 'model_id': runtime['model_id'],
                            'agent_version': runtime['opencode_version'],
                            'tool_versions': {}, 'subagent_policy': 'none'},
                     budget={'kind': 'wall_clock_seconds', 'scope': 'run',
                             'value': runtime['timeout_seconds']})
    return condition


def prepare_prompt(condition, source):
    """Public contract is identical in all arms. No scorer/fixture is read here."""
    request = condition['migration_request']
    common = ('Implement the following modernization in /workspace. The original source is '
              'read-only in /input/legacy-source. Write the final web project under /workspace. '
              'Do not copy the original legacy project or build outputs into the submission. '
              'Inspect the existing code and test your implementation with dotnet. '
              'There is no interactive user during this run.\n\n'
              'Environment: .NET SDK 8; target net8.0. EF Core SQLite 8.0.31 and '
              'Microsoft.Data.Sqlite 8.0.31 are available offline. No Internet access. '
              'Use /tmp for scratch databases.\n\n' + request)
    blocks = []
    method = condition['intervention']['method']
    if method == 'preload':
        patterns = condition['context_files']
        for p in sorted(Path(source).rglob('*')):
            name = p.relative_to(source).as_posix()
            if p.is_file() and any(fnmatch.fnmatch(name, pattern) for pattern in patterns):
                content = p.read_text(encoding='utf-8-sig')
                blocks.append({'source': name, 'text': content})
        if not blocks:
            raise ValueError('Preload matched no source files')
    elif method == 'explained':
        blocks.append({'source': 'public-explanation', 'text': condition['explanation']})
    prompt = common + ''.join('\n\n--- ' + b['source'] + ' ---\n' + b['text'] for b in blocks)
    return prompt, {'method': method, 'common_sha256': util.sha256_bytes(common.encode()),
                    'blocks': [{'source': b['source'], 'sha256': util.sha256_bytes(b['text'].encode()),
                                'text': b['text']} for b in blocks]}


def create(repo, runs_dir, task_id, intervention, attempt, runtime_id='deepseek'):
    repo = Path(repo).resolve()
    condition = resolve(repo, task_id, intervention, runtime_id)
    runtime_root = repo / 'artifacts' / 'runtime' / task_id
    lock = util.read_json(runtime_root / 'lock.json')
    if not lock.get('evaluator_build', {}).get('clean_worktree'):
        raise ValueError('Prepare an evaluator from a clean committed checkout before spending model usage')
    if lock['opencode_version'] != condition['runtime']['opencode_version']:
        raise ValueError('Prepared runtime does not match profile')
    source = repo / 'artifacts' / 'sources' / condition['start_state']['source_commit']
    source_lock = util.read_json(source.parent / (source.name + '.json'))
    if util.tree_hashes(source) != source_lock['files']:
        raise ValueError('Prepared source changed')
    prompt, context = prepare_prompt(condition, source)
    frozen_profiles = {'task': read(repo, 'tasks', task_id),
                       'intervention': read(repo, 'interventions', intervention),
                       'runtime': read(repo, 'runtimes', runtime_id)}
    condition['runtime_lock'] = lock
    condition['agent']['tool_versions'] = lock['versions']
    bundle = runtime_root / 'evaluator'
    if util.tree_hashes(bundle) != lock['evaluator_files']:
        raise ValueError('Prepared evaluator changed')
    condition['evaluation'].update(
        executor='docker', spec_path='evaluation-assets/requirements.json',
        catalog_path='evaluation-assets/catalog.json',
        evaluator_sha256=lock['evaluator_sha256'],
        evaluator_build=lock['evaluator_build'])
    manifest = run.create_run(repo, runs_dir, task_id, intervention, attempt,
                              {'legacy-source': source}, resolved_condition=condition)
    root = Path(runs_dir) / manifest['run_id']
    for name, value in frozen_profiles.items():
        util.write_new_json(root / 'profiles' / (name + '.json'), value)
    assets = root / 'evaluation-assets'
    shutil.copytree(bundle, assets / 'evaluator')
    task = read(repo, 'tasks', task_id)
    for key, dest in [('spec_path', 'requirements.json'), ('catalog_path', 'catalog.json')]:
        shutil.copy2(repo / task['evaluation'][key], assets / dest)
    if util.sha256_file(assets / 'requirements.json') != condition['evaluation']['spec_sha256']:
        raise ValueError('Task ledger hash mismatch; retain incomplete Run')
    (root / 'inputs' / 'prompt.txt').write_bytes(prompt.encode('utf-8'))
    util.write_new_json(root / 'context.json', context)
    manifest.update(schema_version=2, intervention_id=intervention,
                    profile_files=util.tree_hashes(root / 'profiles'),
                    context_sha256=util.sha256_file(root / 'context.json'),
                    prompt_sha256=util.sha256_file(root / 'inputs' / 'prompt.txt'),
                    assets_sha256=util.tree_hashes(assets),
                    input_files=util.tree_hashes(root / 'inputs'))
    run.save_manifest(runs_dir, manifest['run_id'], manifest)
    return manifest


def validate_run(root):
    root = Path(root)
    manifest = util.read_json(root / 'manifest.json')
    if util.sha256_file(root / 'condition.json') != manifest['condition_sha256']:
        raise ValueError('Frozen condition changed')
    if util.tree_hashes(root / 'inputs') != manifest['input_files']:
        raise ValueError('Frozen input changed')
    if util.tree_hashes(root / 'evaluation-assets') != manifest['assets_sha256']:
        raise ValueError('Frozen evaluation assets changed')
    if util.sha256_file(root / 'context.json') != manifest['context_sha256']:
        raise ValueError('Frozen context evidence changed')
    if util.tree_hashes(root / 'profiles') != manifest['profile_files']:
        raise ValueError('Frozen profiles changed')
    return util.read_json(root / 'condition.json')
