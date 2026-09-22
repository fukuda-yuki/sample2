"""Bounded allocated-pair sharing. No model, evaluator, upload or deletion.

Stage explicit evidence, review a new public copy, then package only reviewed
bytes. Restore checks every member before writing into a fresh directory.
This is intentionally not a general publication service or cross-Run database.
"""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import zipfile

from research.catalog_allocation_review import inspect_run, read, sha256, write_new

COHORT = 'runs/catalog-technical-pilot-20260920'
RUNS = ('MS1-001-catalog-compact-001', 'MS1-001-catalog-expanded-001')
PLAN = 'research/protocols/ms1-catalog-technical-pilot-20260920.json'
TEXT_EXTENSIONS = {'.json', '.jsonl', '.txt', '.md', '.log', '.sse', '.cs',
                   '.cshtml', '.csproj', '.sln', '.css', '.js', '.sql', '.py',
                   '.config', '.props', '.targets', '.xml', '.sh'}
SECRET_PATTERNS = {
    'private_key': rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'service_token': rb'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b',
    'bearer_value': rb'(?i)bearer\s+[A-Za-z0-9_.+/=-]{20,}',
    'credential_assignment': rb'(?i)(?:api[_-]?key|access[_-]?token|secret|password)[\s"\x27]*[:=][\s"\x27]*[A-Za-z0-9_+/=-]{24,}',
}


def native(path):
    path = str(Path(path).resolve())
    return Path('\\\\?\\' + path) if os.name == 'nt' and not path.startswith('\\\\?\\') else Path(path)


def files(root):
    root = native(root)
    def fail(exc):
        raise exc
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=fail):
        for name in dirs + names:
            entry = Path(directory) / name
            if entry.is_symlink() or entry.is_junction():
                raise ValueError('Link or junction not supported')
        for name in sorted(names):
            p = Path(directory) / name
            yield p.relative_to(root).as_posix(), p


def inventory(root):
    return {rel: {'bytes': p.stat().st_size, 'sha256': sha256(p)} for rel, p in files(root)}


def exclusion(relative):
    parts = PurePosixPath(relative).parts
    if parts[0] in {'evaluation-assets', 'evaluation-work'}:
        return 'Runtime binaries and duplicate build workspace omitted; evaluator rerun unavailable in this slice.'
    if parts[0] == 'state':
        return 'Private native state and auth/config caches omitted; native events remain in evidence/agent.jsonl.'
    if relative.startswith('inputs/legacy-source/') and not (relative.endswith('/SampleData.cs') or relative.endswith('/readme.txt')):
        return 'Small-slice input subset; full legacy source/assets require the pinned upstream commit and their licenses.'
    if parts[0] == 'workspace':
        return 'Unfrozen workspace omitted; sealed generated source remains in frozen/.'
    if 'browser-state' in parts or relative.endswith(('.sqlite', '.sqlite-wal', '.sqlite-shm')):
        return 'Evaluation DB and WAL omitted; HTTP/browser assertions and traces remain, so independent DB-query replay is unavailable.'
    if relative.endswith('.lock'):
        return 'Operational lock omitted; not an analytical input.'
    if relative.endswith('archive-reference.json'):
        return 'Original archive transport omitted; file hashes in this slice replace its distribution reference.'
    return None


def local_paths_redacted(raw):
    # Replace only the explicit local account-home prefix, preserving JSON escapes.
    home = str(Path.home())
    variants = {home, home.replace('\\', '/'), home.replace('\\', '\\\\')}
    for value in sorted(variants, key=len, reverse=True):
        raw = raw.replace(value.encode(), b'<LOCAL_HOME>')
    return raw


def known_secret():
    if os.name != 'nt':
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
            value, _ = winreg.QueryValueEx(key, 'OPENCODE_GO_API_KEY')
        return value.encode() if value else None
    except FileNotFoundError:
        return None


def scan_bytes(raw, secret=None):
    findings = [name for name, pattern in SECRET_PATTERNS.items() if re.search(pattern, raw)]
    if secret and (secret in raw or secret.decode().encode('utf-16-le') in raw):
        findings.append('existing_provider_credential')
    if local_paths_redacted(raw) != raw:
        findings.append('local_home_path')
    return findings


def scan_file(path, secret=None):
    """Inspect file bytes plus decompressed ZIP content and SQLite text/BLOBs."""
    path = Path(path)
    findings = scan_bytes(path.read_bytes(), secret)
    if path.suffix == '.zip':
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                safe_member(item.filename)
                if item.file_size > 64 * 1024 * 1024:
                    raise ValueError('Trace member exceeds bounded review size')
                findings += ['zip_member:' + x for x in scan_bytes(archive.read(item), secret)]
    if path.suffix == '.db':
        if any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
            raise ValueError('Public SQLite must be sealed')
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            if [r[0] for r in db.execute('PRAGMA integrity_check')] != ['ok']:
                raise ValueError('SQLite integrity failure')
            for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                quoted = '"' + table.replace('"', '""') + '"'
                for row in db.execute('SELECT * FROM ' + quoted):
                    for value in row:
                        if isinstance(value, (str, bytes)):
                            payload = value.encode() if isinstance(value, str) else value
                            findings += ['sqlite_value:' + x for x in scan_bytes(payload, secret)]
    return dict(Counter(findings))


def public_bytes(source):
    raw = source.read_bytes()
    if source.suffix in TEXT_EXTENSIONS:
        raw.decode('utf-8')
        return local_paths_redacted(raw)
    if source.suffix == '.zip':
        result = io.BytesIO()
        changed = False
        with zipfile.ZipFile(io.BytesIO(raw)) as src, zipfile.ZipFile(result, 'w', compression=zipfile.ZIP_DEFLATED) as dst:
            for member in src.infolist():
                safe_member(member.filename)
                value = src.read(member)
                replacement = local_paths_redacted(value)
                if replacement != value:
                    value.decode('utf-8')  # never patch arbitrary binary formats
                    changed = True
                dst.writestr(member, replacement)
        return result.getvalue() if changed else raw
    return raw


def stage(repo, destination, *, plan_path=None, pair=1):
    repo, destination = Path(repo).resolve(), Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(repo / 'runs'):
        raise ValueError('Use a new staging directory outside original Runs')
    plan_path = Path(plan_path or repo / PLAN).resolve()
    plan = read(plan_path)
    if type(pair) is not int or pair < 1:
        raise ValueError('Positive pair number required')
    selected = plan['slots'][(pair - 1) * 2:pair * 2]
    if len(selected) != 2 or {s['condition'] for s in selected} != {'catalog-compact', 'catalog-expanded'}:
        raise ValueError('Select one allocated adjacent pair, including both conditions')
    cohort_path = Path(plan['runs_dir'])
    cohort_path = (repo / cohort_path).resolve()
    if not cohort_path.is_relative_to(repo / 'runs'):
        raise ValueError('Original cohort must be below the repository runs directory')
    cohort = cohort_path.relative_to(repo).as_posix()
    runs = [s['run_id'] for s in selected]
    for name in runs:
        if len(safe_member(name).parts) != 1:
            raise ValueError('Run identity must be a single path component')
    before = {run: inventory(cohort_path / run) if (cohort_path / run).is_dir() else {} for run in runs}
    public = destination / 'public'
    public.mkdir(parents=True)
    manifest = {'schema_version': 1, 'kind': 'pilot_first_pair_sharing_rehearsal',
        'cohort': cohort, 'selected_runs': runs, 'assigned_slots': selected,
        'pair': pair, 'plan_sha256': sha256(plan_path),
        'selection': 'One adjacent allocated pair, selected by slot order, including failures and missing files.',
        'complete_research_corpus': False, 'model_called': False, 'evaluator_called': False,
        'files': [], 'excluded': [], 'original_inventory': before}
    manifest['kind'] = 'catalog_allocated_pair_public_copy'
    manifest['missing_run_directories'] = [run for run in runs if not (cohort_path / run).is_dir()]
    for run in runs:
        for relative, source in files(cohort_path / run) if (cohort_path / run).is_dir() else []:
            target = f'{cohort}/{run}/{relative}'
            reason = exclusion(relative)
            if plan.get('execution') and relative == 'state/catalog-access.json':
                reason = None  # public worker preflight hashes/permissions, not native auth state
            original = before[run][relative]
            if reason:
                manifest['excluded'].append({'path': target, **original, 'reason': reason})
                continue
            out = native(public / target)
            out.parent.mkdir(parents=True, exist_ok=True)
            raw = source.read_bytes()
            transformed = public_bytes(source)
            out.write_bytes(transformed)
            manifest['files'].append({'path': target, 'source_sha256': original['sha256'],
                'bytes': len(transformed), 'sha256': sha256(out),
                'transformation': 'local_home_path_only' if transformed != raw else 'byte_identical'})
    # Read-only tools plus all fixed identities; no evaluator or model entry point.
    plan_relative = plan_path.relative_to(repo).as_posix()
    extra = ['research/sharing/PAIR-README.md'] if plan.get('execution') else []
    # Include the full frozen analysis source and its dependency specification.
    # Distribution remains explicit: original native state and runtime binaries
    # are retained locally, with public exclusions enumerated below.
    if plan.get('execution'):
        extra += list(plan['execution']['code_hashes'])
        extra += ['inner/spec/requirements-1.2.0.json']
        for name in ('launch-receipt.json', 'frozen-plan.json', f'observations-pair-{pair:03d}.json'):
            path = cohort_path / '_control' / name
            if path.exists():
                extra.append(path.relative_to(repo).as_posix())
        # Actual no-model baseline files needed by the existing observation
        # reader to independently check the single intervention/common access.
        probe = (repo / plan['probe']).resolve()
        if probe.is_relative_to(repo) and probe.exists():
            for arm in ('catalog-compact', 'catalog-expanded'):
                baseline = probe / f'MS1-001-{arm}-001'
                names = ['condition.json', 'state/catalog-access.json',
                         'inputs/catalog-derived/raw-first.txt', 'usage/raw/started.jsonl']
                starts = baseline / 'usage/raw/started.jsonl'
                if starts.exists():
                    names += ['usage/raw/' + json.loads(line)['request_file'] for line in starts.read_text(encoding='utf-8').splitlines()]
                for name in names:
                    safe_member(name)
                    path = baseline / name
                    if path.exists():
                        extra.append(path.relative_to(repo).as_posix())
    for rel in dict.fromkeys((plan_relative, 'research/__init__.py', 'research/catalog_allocation_review.py',
                'research/catalog_share.py', 'research/sql/catalog_otel_requests.sql',
                'inner/spec/requirements.json', *extra)):
        out = public / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        raw = (repo / rel).read_bytes()
        transformed = local_paths_redacted(raw)
        fixed_source = plan.get('execution', {}).get('code_hashes', {})
        if plan.get('execution') and (rel == plan_relative or rel in fixed_source) and raw != transformed:
            raise ValueError('Fixed plan/analysis source must be portable before freezing; no hash-changing redaction')
        out.write_bytes(transformed)
        manifest['files'].append({'path': rel, 'source_sha256': sha256(repo / rel),
            'bytes': out.stat().st_size, 'sha256': sha256(out),
            'transformation': 'local_home_path_only' if out.read_bytes() != raw else 'byte_identical'})
    for rel, source in files(repo / 'research/sharing'):
        if rel == 'PAIR-README.md':
            continue
        if rel == 'README.md' and plan.get('execution'):
            source = repo / 'research/sharing/PAIR-README.md'
        out = public / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, out)
        manifest['files'].append({'path': rel, 'source_sha256': sha256(source),
            'bytes': out.stat().st_size, 'sha256': sha256(out), 'transformation': 'byte_identical'})
    # The journal distinguishes an absent directory after uncertain dispatch
    # from an allocated slot that was never sent. Do not infer zero usage.
    journal_path = cohort_path / '_control/journal.jsonl'
    if journal_path.exists():
        rel = 'acquisition-journal.jsonl'
        out = public / rel
        out.write_bytes(local_paths_redacted(journal_path.read_bytes()))
        manifest['files'].append({'path': rel, 'source_sha256': sha256(journal_path),
            'bytes': out.stat().st_size, 'sha256': sha256(out), 'transformation': 'local_home_path_only'})
    manifest['originals_unchanged'] = all(
        (inventory(cohort_path / run) if (cohort_path / run).is_dir() else {}) == before[run] for run in runs)
    if not manifest['originals_unchanged']:
        raise ValueError('Original changed during staging')
    write_new(public / 'MANIFEST.json', manifest)
    write_new(destination / 'stage-receipt.json', {'originals_unchanged': True,
        'included_files': len(manifest['files']), 'excluded_files': len(manifest['excluded']),
        'included_bytes': sum(f['bytes'] for f in manifest['files']),
        'all_original_bytes': sum(f['bytes'] for r in before.values() for f in r.values()),
        'free_bytes_after_staging': shutil.disk_usage(destination).free})


def scan(root, output):
    secret = known_secret()
    findings = []
    count = 0
    for relative, path in files(root):
        result = scan_file(path, secret)
        count += 1
        if result:
            findings.append({'path': relative, 'finding_counts': result})
    write_new(output, {'kind': 'public_copy_machine_scan_not_license_or_visual_acceptance',
        'files_scanned': count, 'known_provider_credential_checked': bool(secret),
        'findings': findings, 'pass': not findings and bool(secret), 'values_logged': False,
        'limitations': 'Pattern checks cannot prove absence of all private context; targeted content, image and license review required.'})


def safe_member(name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or '\\' in name or any(x in ('', '.', '..') for x in name.split('/')):
        raise ValueError('Unsafe archive member')
    if any(':' in x or x.endswith((' ', '.')) for x in p.parts):
        raise ValueError('Unsafe Windows archive member')
    if any(x.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(10)], *[f'LPT{i}' for i in range(10)]} for x in p.parts):
        raise ValueError('Reserved Windows name')
    return p


def verify_public(root):
    manifest = read(native(Path(root) / 'MANIFEST.json'))
    for item in manifest['files']:
        safe_member(item['path'])
        path = native(Path(root) / item['path'])
        if sha256(path) != item['sha256'] or path.stat().st_size != item['bytes']:
            raise ValueError('Public file differs from reviewed manifest')
    return manifest


def pack(root, output, review):
    root, output = Path(root), Path(output)
    verify_public(root)
    decision = read(review)
    current = inventory(root)
    if decision.get('publication_approved') is not True or decision.get('reviewed_inventory') != current:
        raise ValueError('Review must approve the exact public file inventory')
    if output.exists():
        raise FileExistsError(output)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for relative, path in files(root):
            safe_member(relative)
            archive.write(path, relative)
    if output.stat().st_size > 2**30:
        raise ValueError('This bounded rehearsal must fit one <=1 GiB asset; do not upload')
    result = {'kind': 'bounded_release_asset', 'asset': output.name, 'bytes': output.stat().st_size,
        'sha256': sha256(output), 'file_inventory': current, 'review_sha256': sha256(review),
        'assets_after_splitting': 1, 'part_order': [output.name]}
    write_new(output.with_suffix('.manifest.json'), result)


def restore(archive_path, asset_manifest, destination):
    archive_path, destination = Path(archive_path), Path(destination)
    saved = read(asset_manifest)
    if destination.exists():
        raise FileExistsError(destination)
    if archive_path.stat().st_size != saved['bytes'] or sha256(archive_path) != saved['sha256']:
        raise ValueError('Downloaded asset size/hash mismatch')
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(n.casefold() for n in names)) or set(names) != set(saved['file_inventory']):
            raise ValueError('Duplicate or unexpected archive members')
        for item in infos:
            safe_member(item.filename)
            if stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError('Archive symlink refused')
            expected = saved['file_inventory'][item.filename]
            if item.file_size != expected['bytes']:
                raise ValueError('Expanded file size mismatch')
            with archive.open(item) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != expected['sha256']:
                    raise ValueError('Expanded member hash mismatch')
        if shutil.disk_usage(destination.parent).free < sum(i.file_size for i in infos):
            raise ValueError('Insufficient physical space to restore')
        destination.mkdir()
        for item in infos:
            out = native(destination / item.filename)
            out.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, out.open('xb') as target:
                shutil.copyfileobj(source, target)
    if inventory(destination) != saved['file_inventory']:
        raise ValueError('Restored tree differs')
    verify_public(destination)
    return {'asset_sha256': saved['sha256'], 'files_verified': len(infos), 'hashes_match': True}


def extract(root):
    """Use original SQL and normalized totals; never import or score a product."""
    root = native(root)
    manifest = verify_public(root)
    sql = (root / 'research/sql/catalog_otel_requests.sql').read_text(encoding='utf-8')
    results = []
    for run in manifest.get('selected_runs', RUNS):
        run_root = root / manifest.get('cohort', COHORT) / run
        if not (run_root / 'telemetry/monitor.db').exists():
            results.append({'run_id': run, 'sqlite': None, 'requests': None,
                'evaluation_attempts': saved_attempts(run_root),
                'missing_evidence': 'No sealed gateway database; usage remains unknown, not zero.'})
            continue
        try:
            reviewed = inspect_run(run_root)
        except (FileNotFoundError, KeyError, ValueError, sqlite3.DatabaseError) as exc:
            results.append({'run_id': run, 'sqlite': None, 'requests': None,
                'evaluation_attempts': saved_attempts(run_root),
                'inspection_error_type': type(exc).__name__,
                'missing_evidence': 'Gateway evidence is incomplete or inconsistent; originals are retained and totals remain unknown.'})
            continue
        with closing(sqlite3.connect((run_root / 'telemetry/monitor.db').resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            db.row_factory = sqlite3.Row
            rows = [dict(r) for r in db.execute(sql)]
        if len(rows) != reviewed['request_spans'] or any(r['run_id'] != run for r in rows):
            raise ValueError('Restored SQL identities differ')
        for key in ('input_tokens', 'output_tokens', 'cache_read_tokens'):
            if reviewed[key] is not None and (any(r[key] is None for r in rows) or sum(r[key] for r in rows) != reviewed[key]):
                raise ValueError('SQL token projection mismatch')
        attempts = saved_attempts(run_root)
        results.append({'run_id': run, 'sqlite': reviewed, 'requests': rows,
            'evaluation_attempts': [{k: a.get(k) for k in ('sequence','adopted','scoring_state','verdict','quality','directory')} for a in attempts]})
    kind = ('restored_pilot_offline_extraction_not_reevaluation' if manifest.get('kind') == 'pilot_first_pair_sharing_rehearsal'
            else 'restored_catalog_pair_offline_extraction_not_reevaluation')
    return {'kind': kind, 'model_called': False,
        'evaluator_called': False, 'human_review': 'not_run', 'runs': results}


def saved_attempts(root):
    root = native(root)
    path = root / 'evaluations/index.jsonl'
    attempts = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []
    for attempt in attempts:
        directory = safe_member(attempt['directory'])
        if not (root / directory / 'evaluation.json').is_file():
            raise ValueError('An evaluation attempt was lost')
    return attempts


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=('stage', 'scan', 'pack', 'restore', 'extract'))
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--review', type=Path)
    p.add_argument('--asset-manifest', type=Path)
    p.add_argument('--plan', type=Path)
    p.add_argument('--pair', type=int, default=1)
    a = p.parse_args()
    if a.mode == 'stage':
        stage(a.root, a.out, plan_path=a.plan, pair=a.pair)
    elif a.mode == 'scan':
        scan(a.root, a.out)
    elif a.mode == 'pack':
        pack(a.root, a.out, a.review)
    elif a.mode == 'restore':
        print(json.dumps(restore(a.root, a.asset_manifest, a.out)))
    else:
        write_new(a.out, extract(a.root))


if __name__ == '__main__':
    main()
