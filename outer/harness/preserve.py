"""Researcher-only, append-only directory packages with verified restoration.

No credentials discovery and no implicit recursive capture of a Run workspace.
Callers provide an explicit allowlist of sources. Packages contain ordinary files
only; restored executable mode bits are retained for Linux runtimes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import uuid


def native_path(path):
    """Use Windows extended paths without changing machine-wide path policy."""
    path = Path(path).absolute()
    name = str(path)
    if os.name == 'nt' and not name.startswith('\\\\?\\'):
        name = ('\\\\?\\UNC\\' + name[2:]) if name.startswith('\\\\') else '\\\\?\\' + name
    return Path(name)


def read(path):
    return json.loads(native_path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    h = hashlib.sha256()
    with native_path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_new(path, value):
    path = native_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def safe_name(name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or any(p in ('', '.', '..') for p in name.split('/'))
            or PurePosixPath(name).is_absolute()):
        raise ValueError('Unsafe package path')
    return name


def tree(root):
    root = native_path(root)
    if root.is_symlink() or (hasattr(root, 'is_junction') and root.is_junction()):
        raise ValueError('Links forbidden')
    entries = {}
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            p = Path(base) / name
            if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
                raise ValueError('Links forbidden: ' + str(p))
            if not (p.is_file() or p.is_dir()):
                raise ValueError('Special files forbidden')
        for name in sorted(files):
            p = Path(base) / name
            relative = safe_name(p.relative_to(root).as_posix())
            entries[relative] = {'sha256': digest(p), 'bytes': p.stat().st_size,
                                 'executable': bool(p.stat().st_mode & stat.S_IXUSR)}
    return dict(sorted(entries.items()))


def content_equal(actual, expected):
    # Windows/DrvFS may not preserve Unix mode bits. Restore applies recorded modes.
    return ({k: (v['sha256'], v['bytes']) for k, v in actual.items()}
            == {k: (v['sha256'], v['bytes']) for k, v in expected.items()})


def verify(archive, package_id, expected_hash=None, seen=None, cache=None):
    cache = {} if cache is None else cache
    safe_name(package_id)
    if '/' in package_id:
        raise ValueError('Package ID must be one component')
    package = native_path(archive) / 'packages' / package_id
    if package.is_symlink():
        raise ValueError('Package link forbidden')
    index = package / 'package.json'
    if expected_hash and digest(index) != expected_hash:
        raise ValueError('Package index changed')
    cache_key = (str(Path(archive).resolve()), package_id, digest(index))
    if cache_key in cache:
        return cache[cache_key]
    data = read(index)
    if data['package_id'] != package_id or data['schema_version'] != 1:
        raise ValueError('Package identity mismatch')
    if set(p.name for p in package.iterdir()) != {'package.json', 'payload'}:
        raise ValueError('Unexpected package member')
    for name in data['files']:
        safe_name(name)
    if not content_equal(tree(package / 'payload'), data['files']):
        raise ValueError('Package missing, extra or modified file')
    seen = set() if seen is None else set(seen)
    if package_id in seen:
        raise ValueError('Cyclic package references')
    seen.add(package_id)
    for ref in data['references']:
        verify(archive, ref['package_id'], ref['sha256'], seen, cache)
    cache[cache_key] = data
    return data


def pack(archive, package_id, sources, *, metadata=None, references=()):
    archive = native_path(archive).resolve()
    safe_name(package_id)
    if '/' in package_id:
        raise ValueError('Package ID must be one component')
    packages = archive / 'packages'
    packages.mkdir(parents=True, exist_ok=True)
    final = packages / package_id
    # Persistent reservation also records failed packaging attempts; never reuse IDs.
    write_new(archive / 'package-reservations' / (package_id + '.json'),
              {'package_id': package_id, 'started_at': datetime.now(timezone.utc).isoformat()})
    temporary = packages / ('.partial-' + package_id + '-' + str(uuid.uuid4()))
    payload = temporary / 'payload'
    payload.mkdir(parents=True)
    for relative, source in sources.items():
        safe_name(relative)
        source = native_path(source)
        if source.is_symlink() or (hasattr(source, 'is_junction') and source.is_junction()):
            raise ValueError('Source link forbidden')
        source = source.resolve(strict=True)
        if archive == source or archive.is_relative_to(source) or source.is_relative_to(archive):
            raise ValueError('Archive and sources must be independent')
        destination = payload / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            before = tree(source)
            shutil.copytree(source, destination)
            if not content_equal(tree(destination), before) or not content_equal(tree(source), before):
                raise ValueError('Source changed during copy')
        else:
            if source.is_symlink() or not source.is_file():
                raise ValueError('Regular sources required')
            before = digest(source)
            shutil.copy2(source, destination)
            if digest(source) != before or digest(destination) != before:
                raise ValueError('Source changed during copy')
    for ref in references:
        verify(archive, ref['package_id'], ref['sha256'])
    data = {'schema_version': 1, 'package_id': package_id,
            'created_at': datetime.now(timezone.utc).isoformat(), 'metadata': metadata or {},
            'references': list(references), 'files': tree(payload)}
    write_new(temporary / 'package.json', data)
    if not content_equal(tree(payload), data['files']):
        raise ValueError('Copy verification failed')
    if final.exists():
        raise FileExistsError(final)
    temporary.rename(final)
    return {'package_id': package_id, 'sha256': digest(final / 'package.json')}


def ensure_package(archive, package_id, sources, *, metadata=None, references=()):
    """Recover a committed package whose receipt write was interrupted, without overwriting."""
    final=native_path(archive)/'packages'/safe_name(package_id)
    if final.exists():
        data=verify(archive,package_id)
        expected={}
        for name,source in sources.items():
            safe_name(name);source=native_path(source)
            if source.is_symlink() or source.is_junction():raise ValueError('Source link forbidden')
            if source.is_dir():expected.update({name+'/'+n:e for n,e in tree(source).items()})
            else:expected[name]={'sha256':digest(source),'bytes':source.stat().st_size}
        if (not content_equal(data['files'],expected) or data['metadata']!=(metadata or {})
                or data['references']!=list(references)):
            raise ValueError('Committed package differs from interrupted request')
        return {'package_id':package_id,'sha256':digest(final/'package.json')}
    if (Path(archive)/'package-reservations'/(package_id+'.json')).exists():
        package_id+='-retry-'+str(uuid.uuid4())
    return pack(archive,package_id,sources,metadata=metadata,references=references)


def restore(archive, reference, destination, *, resume=False):
    archive, destination = native_path(archive).resolve(), native_path(destination)
    if destination.is_relative_to(archive) or archive.is_relative_to(destination):
        raise ValueError('Restore must be independent of archive')
    data = verify(archive, reference['package_id'], reference['sha256'])
    source = archive / 'packages' / reference['package_id'] / 'payload'
    claim=destination.parent/('.'+destination.name+'.restore-request.json')
    binding={'reference':reference,'destination':str(destination)}
    if claim.exists():
        original=read(claim)
        if any(original.get(k)!=v for k,v in binding.items()):raise ValueError('Restoration request binding changed')
    else:
        original=dict(binding,status='copying')
        # Existing legacy copies may only be adopted after full hash verification.
        if destination.exists() and not content_equal(tree(destination),data['files']):
            raise ValueError('Unowned partial restoration must be retained')
        write_new(claim,original)
    if destination.exists():
        if not resume:
            raise ValueError('Existing restoration is incomplete or changed; retain it')
        if not content_equal(tree(destination),data['files']):
            if original.get('status')!='copying':raise ValueError('Completed restoration changed')
            retained=destination.with_name(destination.name+'.interrupted-'+str(uuid.uuid4()))
            if not destination.resolve().is_relative_to(destination.parent.resolve()) or not retained.resolve().is_relative_to(destination.parent.resolve()):
                raise ValueError('Restoration recovery path escaped its parent')
            destination.rename(retained)
            shutil.copytree(source,destination)
    else:shutil.copytree(source, destination)
    for name, entry in data['files'].items():
        (destination / name).chmod(0o755 if entry['executable'] else 0o644)
    if not content_equal(tree(destination), data['files']):
        raise ValueError('Restoration mismatch')
    verify(archive, reference['package_id'], reference['sha256'])
    receipt = {'schema_version': 1, 'reference': reference, 'restored_to': str(destination),
               'verified_at': datetime.now(timezone.utc).isoformat(), 'file_count': len(data['files'])}
    receipt_id = str(uuid.uuid4())
    target = archive / 'receipts' / (receipt_id + '.json')
    write_new(target, receipt)
    temporary=claim.with_name(claim.name+'.'+str(uuid.uuid4())+'.tmp')
    write_new(temporary,dict(binding,status='completed',receipt={'path':'receipts/'+receipt_id+'.json','sha256':digest(target)}))
    temporary.replace(claim)
    return {'path': 'receipts/' + receipt_id + '.json', 'sha256': digest(target)}


def verify_receipt(archive, receipt, cache=None):
    safe_name(receipt['path'])
    path = Path(archive) / receipt['path']
    if digest(path) != receipt['sha256']:
        raise ValueError('Restore receipt changed')
    data = read(path)
    verify(archive, data['reference']['package_id'], data['reference']['sha256'], cache=cache)
    return data


PACK_NAMES = ('frozen', 'snapshot.json', 'manifest.json', 'condition.json',
              'inputs-manifest.json', 'inputs', 'usage', 'evaluations')
OPTIONAL_NAMES = ('workspace', 'evidence')


def pack_run(archive, run_root, references=(), include=()):
    """Pack the evidence of one run. The workspace is intermediate and large, so it is
    packed only when asked for; that is recorded separately from a missing file."""
    root = Path(run_root)
    manifest = read(root / 'manifest.json')
    include = [name for name in include if name in OPTIONAL_NAMES]
    names = list(PACK_NAMES) + include
    required = list(PACK_NAMES)
    if manifest.get('schema_version') == 2:
        names += ['evaluation-assets', 'profiles', 'context.json', 'runtime.json', 'telemetry',
                  'telemetry-link.json', 'state', 'stop-request.json', 'stop-result.json', 'evaluation-work']
        names += [p.name for p in root.glob('pipeline-error-*.json')]
        required += ['profiles', 'evaluation-assets', 'context.json', 'runtime.json', 'state', 'telemetry-link.json']
    sources = {name: root / name for name in names if (root / name).exists()}
    metadata = {'kind': 'run', 'run_id': manifest['run_id'],
                'missing': [name for name in required if name not in sources],
                'skipped_by_choice': [name for name in OPTIONAL_NAMES if name not in sources],
                'stop_confirmed': manifest.get('stop_confirmed'),
                'submission_fixed': manifest.get('submission_fixed'),
                'end_reason': manifest.get('end_reason')}
    package_id = 'run-' + manifest['run_id']
    if manifest.get('schema_version') == 2 and (native_path(archive) / 'package-reservations' / (package_id + '.json')).exists():
        package_id += '-revision-' + uuid.uuid4().hex[:12]
    return pack(archive, package_id, sources,
                metadata=metadata, references=references)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['pack', 'restore', 'verify'])
    parser.add_argument('archive', type=Path)
    parser.add_argument('spec', type=Path, help='Explicit sources or pinned package reference JSON')
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    spec = read(args.spec)
    if args.operation == 'pack':
        result = pack(args.archive, spec['package_id'], spec['sources'],
                      metadata=spec.get('metadata'), references=spec.get('references', []))
    elif args.operation == 'restore':
        result = restore(args.archive, spec, args.destination)
    else:
        result = verify(args.archive, spec['package_id'], spec['sha256'])
    print(json.dumps(result, ensure_ascii=False))
