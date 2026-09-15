"""Shared primitives for the outer harness.

Only standard library. No model client, no network access.
"""
import hashlib
import json
import os
import uuid
from pathlib import Path

# Collection excludes. Must be a superset of the evaluator's exclusions
# (bin, obj, .git) or the artifact hash the evaluator computes will differ.
EXCLUDED_DIRECTORIES = ('bin', 'obj', '.git', '.vs', 'node_modules', 'TestResults')
EXCLUDED_SUFFIXES = ('.sqlite', '.sqlite3', '.db', '.db-shm', '.db-wal', '.user')

# Text files whose line endings and BOM are fixed at collection time.
# The evaluation ID depends on the artifact bytes, so the bytes must not
# depend on the checkout's line-ending configuration.
NORMALIZED_SUFFIXES = (
    '.cs', '.csproj', '.cshtml', '.config', '.json', '.jsonl', '.md', '.txt',
    '.css', '.js', '.html', '.xml', '.razor', '.sln', '.props', '.targets',
    '.yml', '.yaml', '.csv', '.ps1', '.sh',
)

BOM = b'\xef\xbb\xbf'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_new_json(path, value):
    """Exclusive create. Never overwrites an existing record."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def write_json_atomic(path, value):
    """Replace a mutable record (the run manifest). Not used for packages."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temp.open('w', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def append_line(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def read_lines(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def is_excluded(relative_parts):
    return any(part.lower() in EXCLUDED_DIRECTORIES for part in relative_parts)


def artifact_files(root):
    """Files that the evaluator counts, in the evaluator's order.

    The evaluator orders by the Windows relative path (backslash separated)
    with StringComparer.Ordinal. Sorting the forward-slash form instead would
    reorder paths that differ only around '/' versus a character between
    '/' and '\\' (digits, ':', uppercase letters, '['), so the backslash form
    is what gets sorted here too.

    The evaluator's own exclusions are directories only. EXCLUDED_SUFFIXES is
    applied here as well because collection drops those files from frozen/:
    the frozen directory never holds them, so the two hashes still agree.
    """
    root = Path(root)
    files = []
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if is_excluded(relative.parts) or path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        files.append(str(relative))
    return sorted(files)


def artifact_hash(root):
    """Byte identity of an artifact directory.

    Same algorithm as the evaluator's Sha256Directory: for every file not under
    bin/obj/.git, append "<forward-slash relative path> <sha256>\n" in the
    evaluator's order, then hash the UTF-8 bytes.
    """
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(root)
    builder = []
    for relative in artifact_files(root):
        builder.append(relative.replace('\\', '/'))
        builder.append(' ')
        builder.append(sha256_file(root / relative))
        builder.append('\n')
    return sha256_bytes(''.join(builder).encode('utf-8'))


def normalize_text(data):
    """Return (fixed_bytes, kinds). Kinds describe what was changed."""
    kinds = []
    if data.startswith(BOM):
        data = data[len(BOM):]
        kinds.append('bom_removed')
    if b'\r' in data:
        data = data.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
        kinds.append('crlf_to_lf')
    return data, kinds


def collect(workspace, frozen, *, normalize=True):
    """Copy workspace to frozen, excluding generated files and fixing text bytes."""
    workspace, frozen = Path(workspace), Path(frozen)
    if frozen.exists():
        raise FileExistsError(frozen)
    if not workspace.is_dir():
        raise FileNotFoundError(workspace)
    frozen.mkdir(parents=True)
    collected, fixed, normalized = {}, {}, []
    excluded = []
    for path in sorted(workspace.rglob('*'), key=lambda p: str(p.relative_to(workspace))):
        relative = path.relative_to(workspace)
        if is_excluded(relative.parts):
            continue
        name = str(relative).replace('\\', '/')
        if path.is_dir():
            (frozen / relative).mkdir(parents=True, exist_ok=True)
            continue
        if not path.is_file():
            raise ValueError('Special files are not collectable: ' + name)
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            excluded.append(name)
            continue
        data = path.read_bytes()
        collected[name] = {'sha256': sha256_bytes(data), 'bytes': len(data)}
        kinds = []
        if normalize and path.suffix.lower() in NORMALIZED_SUFFIXES:
            data, kinds = normalize_text(data)
        (frozen / relative).parent.mkdir(parents=True, exist_ok=True)
        with (frozen / relative).open('wb') as stream:
            stream.write(data)
        fixed[name] = {'sha256': sha256_bytes(data), 'bytes': len(data)}
        if kinds:
            normalized.append({'path': name, 'changed': kinds})
    return {'collected': collected, 'frozen': fixed, 'normalized': normalized,
            'excluded_files': excluded,
            'excluded_directories': list(EXCLUDED_DIRECTORIES),
            'excluded_suffixes': list(EXCLUDED_SUFFIXES)}


def tree_hashes(root):
    """Relative path -> {sha256, bytes} for every regular file under root."""
    root = Path(root)
    entries = {}
    for path in sorted(root.rglob('*'), key=lambda p: str(p.relative_to(root))):
        if path.is_file():
            entries[str(path.relative_to(root)).replace('\\', '/')] = {
                'sha256': sha256_file(path), 'bytes': path.stat().st_size}
    return entries
