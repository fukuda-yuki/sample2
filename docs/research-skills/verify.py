"""Offline installation audit; never dispatches models, Docker, or evaluators."""
import hashlib
import json
from pathlib import Path
import re
import sys


REPO = Path(__file__).resolve().parents[2]
EXPECTED = {
    'research-analysis', 'scientific-critical-thinking', 'hypothesis-generation',
    'scientific-brainstorming', 'creative-thinking-for-research',
    'brainstorming-research-ideas',
}


def verify():
    manifest = json.loads((REPO / 'docs/research-skills/manifest.json').read_text())
    errors = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    def local_path(relative):
        path = REPO / relative
        require(not Path(relative).is_absolute() and '..' not in Path(relative).parts,
                f'Unsafe manifest path: {relative}')
        require(path.resolve().is_relative_to(REPO), f'Path outside repository: {relative}')
        require(not any(p.is_symlink() for p in [path, *path.parents] if p != REPO),
                f'Symlink in manifest path: {relative}')
        return path

    require(manifest['scope'] == 'post-acquisition-analysis-and-interpretation-only',
            'Manifest must restrict use to analysis and interpretation')
    require(manifest['global_install'] is False and manifest['sampling_activation'] is False,
            'Global installation or sampling activation is forbidden')
    names = {entry['name'] for entry in manifest['local_entrypoints']}
    require(names == EXPECTED, f'Unexpected entrypoints: {names ^ EXPECTED}')
    require(len(manifest['local_entrypoints']) == len(EXPECTED), 'Duplicate entrypoint')
    records = list(manifest['local_entrypoints'])
    for bundle in manifest['bundles']:
        require(bool(re.fullmatch(r'[0-9a-f]{40}', bundle['commit'])),
                f"Unpinned source: {bundle['id']}")
        require(bundle['license'] in {'MIT', 'CC0-1.0'}, f"Unexpected license: {bundle['id']}")
        require(any(x['local_path'].endswith('/LICENSE.txt') for x in bundle['files']),
                f"Missing license: {bundle['id']}")
        records.extend(bundle['files'])
    records.extend(manifest['protected_experiment_files'])
    for record in records:
        path = local_path(record['local_path'])
        if not path.is_file():
            errors.append(f'Missing file: {record["local_path"]}')
            continue
        require(hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256'],
                f'Changed bytes: {record["local_path"]}')

    skill_root = REPO / '.agents/skills'
    installed = {str(p.relative_to(REPO)) for p in skill_root.rglob('*') if p.is_file()}
    declared = {x['local_path'] for x in records if x['local_path'].startswith('.agents/skills/')}
    require(installed == declared, f'Undeclared or missing Skill files: {installed ^ declared}')
    require({p.parent.name for p in skill_root.glob('*/SKILL.md')} == EXPECTED,
            'Unexpected discoverable Skill')
    require(not list(skill_root.rglob('scripts')), 'Bundled scripts were not approved for this subset')
    require(all(Path(p).suffix in {'.md', '.txt', '.json', '.csv'} for p in installed),
            'Executable/dependency file in documentation-only Skill subset')

    # Audit live entrypoint references; upstream examples have explicitly omitted CLIs.
    link_files = [REPO / x['local_path'] for x in manifest['local_entrypoints']]
    link_files += [REPO / 'docs/research-skills/README.md']
    checked_links = 0
    for path in link_files:
        if not path.is_file():
            continue
        content = path.read_text()
        if path.name == 'SKILL.md':
            require(content.startswith('---\n'), f'Missing frontmatter: {path}')
            require(f'\nname: {path.parent.name}\n' in content, f'Name mismatch: {path}')
            require('description:' in content and 'sampling' in content,
                    f'Missing scope in discoverable description: {path}')
        for target in re.findall(r'\]\(([^)]+)\)', content):
            if '://' in target or target.startswith('#'):
                continue
            destination = (path.parent / target.split('#')[0]).resolve()
            require(destination.is_relative_to(REPO) and destination.is_file(),
                    f'Broken local reference in {path.relative_to(REPO)}: {target}')
            checked_links += 1

    agents = (REPO / 'AGENTS.md').read_text()
    require('.agents/skills/research-analysis/SKILL.md' in agents, 'Missing AGENTS entrypoint')
    require('データ取得（サンプリング）' in agents and 'では起動しない' in agents,
            'Missing non-activation rule')
    ignored = set((REPO / '.dockerignore').read_text().splitlines())
    require({'.agents', 'AGENTS.md'} <= ignored, 'Research instructions in Docker build context')
    require(bool(manifest['protected_experiment_files']), 'Missing experiment boundary baseline')
    return {
        'status': 'passed' if not errors else 'failed',
        'active_entrypoints': len(names),
        'imported_files': sum(len(x['files']) for x in manifest['bundles']),
        'local_links_checked': checked_links,
        'protected_experiment_files_unchanged': len(manifest['protected_experiment_files']),
        'checks': 'file hashes, pinned sources, licenses, local links, scope, documentation-only subset, Docker exclusions',
        'limits': 'Static audit only. Does not prove automatic discovery, activation, scientific effectiveness, or live worker isolation.',
        'errors': errors,
    }


if __name__ == '__main__':
    result = verify()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result['status'] == 'passed' else 1)
