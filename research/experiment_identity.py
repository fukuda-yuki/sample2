"""Offline identity/storage adapter for future campaigns and saved reassessments.

No dispatch, provider, Docker, scoring, Git, or publication action lives here.
Historical next_phase/wave contracts intentionally remain unchanged. The lease
is an exclusive scope marker, not proof that an external worker has stopped.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import uuid
import zipfile
from outer.harness import util

SCHEMA = 1
MAX_PACKAGE_BYTES = 256 * 1024 * 1024
READER_FILES = ('report/REPORT.md', 'REPRODUCE.md')


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', value):
        raise ValueError('Unsafe identity component')
    if value.upper() in {'CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(1, 10)],
                         *[f'LPT{i}' for i in range(1, 10)]}:
        raise ValueError('Reserved identity component')
    return value


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ValueError('Expected SHA256')
    return value


def _version(value):
    if not isinstance(value, str) or len(value) > 96 or not re.fullmatch(r'[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*', value):
        raise ValueError('Expected explicit evaluation version')
    return value


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Expected canonical UUID')
    return value


def _source_uuid(value):
    if not isinstance(value, str): raise ValueError('Expected source Run UUID')
    parsed = uuid.UUID(value)
    if value not in (str(parsed), parsed.hex): raise ValueError('Noncanonical source Run UUID')
    return value


def _relative(value):
    if not isinstance(value, str) or re.search(r'[\\:<>"|?*\x00-\x1f]', value):
        raise ValueError('Expected portable relative path')
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix() or any(p in ('.', '..') for p in path.parts) or not path.parts:
        raise ValueError('Unsafe relative path')
    for part in path.parts:
        if part.endswith(('.', ' ')) or part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                *[f'COM{i}' for i in range(1, 10)], *[f'LPT{i}' for i in range(1, 10)]}:
            raise ValueError('Nonportable path component')
    return path


def _inside(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError('Path must remain beneath its owned root')
    return path


def sha256_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode('utf8')


def _new_json(path, value):
    with Path(path).open('xb') as stream:
        stream.write(_json_bytes(value))


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def _identity(value):
    if not isinstance(value, dict) or type(value.get('schema_version')) is not int or value.get('schema_version') != SCHEMA:
        raise ValueError('Unknown identity schema')
    allowed = {'schema_version', 'kind', 'campaign_id', 'campaign_uuid', 'evaluation_version', 'evaluator_sha256'}
    _name(value['campaign_id']); _uuid(value['campaign_uuid'])
    _version(value['evaluation_version']); _sha(value['evaluator_sha256'])
    if value['kind'] == 'new_acquisition_campaign':
        allowed.add('plan_sha256')
        _sha(value['plan_sha256'])
    elif value['kind'] == 'saved_artifact_reassessment':
        allowed.update({'assessment_id', 'assessment_label', 'source_run_instance_id',
            'source_artifact_sha256', 'source_run_identity_sha256', 'source_artifact_path',
            'source_evaluation_version', 'source_condition_sha256', 'source_snapshot_sha256',
            'source_campaign_binding'})
        _uuid(value['assessment_id']); _name(value['assessment_label'])
        _source_uuid(value['source_run_instance_id']); _sha(value['source_artifact_sha256'])
        _sha(value['source_run_identity_sha256']); _relative(value['source_artifact_path'])
        _version(value['source_evaluation_version'])
        for field in ('source_condition_sha256', 'source_snapshot_sha256'):
            if field in value: _sha(value[field])
        if value.get('source_campaign_binding') not in (
                'verified_local_campaign_metadata', 'caller_asserted_unverified'):
            raise ValueError('Source campaign binding confidence must be explicit')
    else:
        raise ValueError('Acquisition and reassessment must be distinct kinds')
    if set(value) - allowed: raise ValueError('Unreviewed identity fields cannot be published')
    return value


@dataclass(frozen=True)
class Campaign:
    root: Path
    metadata: dict

    @property
    def campaign_uuid(self): return self.metadata['campaign_uuid']

    @property
    def public_workspace(self): return _inside(self.root, self.root / 'publication')

    def _check(self):
        _identity(self.metadata)
        if self.metadata != _read(self.root / 'campaign.json'):
            raise ValueError('Campaign identity changed')

    def create_run(self, label):
        self._check(); _name(label)
        root = _inside(self.root, self.root / 'runs' / label)
        root.mkdir(parents=True, exist_ok=False)
        (root / 'output').mkdir()
        value = {'schema_version': SCHEMA, 'kind': 'acquisition_run',
                 'campaign_uuid': self.campaign_uuid, 'campaign_id': self.metadata['campaign_id'],
                 'run_label': label, 'run_instance_id': str(uuid.uuid4())}
        _new_json(root / 'run.json', value)
        return value

    def run_root(self, run):
        self._check()
        if run.get('campaign_uuid') != self.campaign_uuid or run.get('campaign_id') != self.metadata['campaign_id']:
            raise ValueError('Run belongs to another campaign')
        _name(run['run_label']); _uuid(run['run_instance_id'])
        path = _inside(self.root, self.root / 'runs' / run['run_label'])
        if _read(path / 'run.json') != run:
            raise ValueError('Run identity mismatch')
        return path

    def output_root(self, run): return _inside(self.root, self.run_root(run) / 'output')

    def acquire_lease(self):
        self._check()
        lease = {'campaign_uuid': self.campaign_uuid, 'generation': str(uuid.uuid4())}
        _new_json(self.root / '_control' / 'lease.json', lease)
        return lease

    def _lease(self, lease):
        self._check()
        if lease.get('campaign_uuid') != self.campaign_uuid or _read(self.root / '_control' / 'lease.json') != lease:
            raise ValueError('Foreign or stale lease')
        _uuid(lease['generation'])

    def release_lease(self, lease):
        self._lease(lease)
        (self.root / '_control' / 'lease.json').unlink()

    def request_stop(self, lease, *, reason):
        self._lease(lease)
        if not isinstance(reason, str) or not reason.strip(): raise ValueError('STOP reason required')
        _new_json(self.root / '_control' / ('stop-' + lease['generation'] + '.json'),
                  {**lease, 'reason': reason})

    def stop_requested(self, lease):
        self._lease(lease)
        path = self.root / '_control' / ('stop-' + lease['generation'] + '.json')
        if not path.exists(): return False
        stop = _read(path)
        if any(stop.get(k) != lease[k] for k in ('campaign_uuid', 'generation')):
            raise ValueError('STOP scope mismatch')
        return True


def create_campaign(base, campaign_id, *, plan_sha256, evaluation_version, evaluator_sha256):
    metadata = _identity({'schema_version': SCHEMA, 'kind': 'new_acquisition_campaign',
        'campaign_id': _name(campaign_id), 'campaign_uuid': str(uuid.uuid4()),
        'plan_sha256': _sha(plan_sha256), 'evaluation_version': _version(evaluation_version),
        'evaluator_sha256': _sha(evaluator_sha256)})
    root = _inside(base, Path(base) / 'campaigns' / campaign_id)
    root.mkdir(parents=True, exist_ok=False)
    for folder in ('runs', '_control', 'publication'): (root / folder).mkdir()
    _new_json(root / 'campaign.json', metadata)
    return Campaign(root, metadata)


def create_reassessment(base, label, *, source, source_run, artifact, artifact_sha256,
                        evaluation_version, evaluator_sha256):
    """Bind a separate assessment to an immutable source, without invoking scoring."""
    _name(label)
    if evaluation_version == source.metadata['evaluation_version']:
        raise ValueError('Reassessment requires a distinct evaluation version')
    run_root = source.run_root(source_run)
    artifact = _inside(run_root, artifact)
    if not artifact.is_file() or sha256_file(artifact) != _sha(artifact_sha256):
        raise ValueError('Source artifact hash mismatch')
    value = _identity({'schema_version': SCHEMA, 'kind': 'saved_artifact_reassessment',
        'campaign_id': source.metadata['campaign_id'], 'campaign_uuid': source.campaign_uuid,
        'assessment_label': label, 'assessment_id': str(uuid.uuid4()),
        'source_run_instance_id': source_run['run_instance_id'],
        'source_run_identity_sha256': sha256_file(run_root / 'run.json'),
        'source_artifact_sha256': artifact_sha256,
        'source_artifact_path': artifact.relative_to(run_root).as_posix(),
        'source_evaluation_version': source.metadata['evaluation_version'],
        'source_campaign_binding': 'verified_local_campaign_metadata',
        'evaluation_version': _version(evaluation_version), 'evaluator_sha256': _sha(evaluator_sha256)})
    root = _inside(base, Path(base) / 'assessments' / label)
    if root.is_relative_to(source.root): raise ValueError('Assessment storage would modify source campaign')
    root.mkdir(parents=True, exist_ok=False)
    _new_json(root / 'assessment.json', value)
    return value


def create_frozen_reassessment(base, label, *, source_run_root, source_campaign_id,
                              source_campaign_uuid, evaluation_version, evaluator_sha256):
    """Read-only import of an existing schema-2 frozen Run, not a new acquisition.

    The campaign UUID is the caller's stable experiment-registry identity; it
    does not replace any original Run UUID. All three source metadata files and
    the SDK artifact tree are bound before creating an assessment directory.
    """
    _name(label); _name(source_campaign_id); _uuid(source_campaign_uuid)
    source = Path(source_run_root).resolve()
    if Path(base).resolve().is_relative_to(source):
        raise ValueError('Assessment storage must not be within the source Run')
    util.reject_links(source / 'frozen')
    manifest = util.read_json(source / 'manifest.json')
    snapshot = util.read_json(source / 'snapshot.json')
    condition = util.read_json(source / 'condition.json')
    if manifest.get('schema_version') != 2 or condition.get('schema_version') != 2:
        raise ValueError('Only schema-2 fixed source Runs are supported')
    if manifest.get('stop_confirmed') is not True or manifest.get('submission_fixed') is not True:
        raise ValueError('Source Run is not stopped and fixed')
    if snapshot.get('run_id') != manifest.get('run_id'):
        raise ValueError('Source snapshot Run mismatch')
    _source_uuid(manifest['run_instance_id'])
    if sha256_file(source / 'condition.json') != _sha(manifest['condition_sha256']):
        raise ValueError('Source condition hash mismatch')
    artifact_sha256 = _sha(snapshot['artifact_sha256'])
    if util.artifact_hash(source / 'frozen') != artifact_sha256:
        raise ValueError('Source frozen artifact hash mismatch')
    old_version = condition['evaluation']['evaluation_version']
    if evaluation_version == old_version:
        raise ValueError('Reassessment requires a distinct evaluation version')
    value = _identity({'schema_version': SCHEMA, 'kind': 'saved_artifact_reassessment',
        'campaign_id': source_campaign_id, 'campaign_uuid': source_campaign_uuid,
        'assessment_label': label, 'assessment_id': str(uuid.uuid4()),
        'source_run_instance_id': manifest['run_instance_id'],
        'source_run_identity_sha256': sha256_file(source / 'manifest.json'),
        'source_artifact_sha256': artifact_sha256, 'source_artifact_path': 'frozen',
        'source_evaluation_version': old_version,
        'source_campaign_binding': 'caller_asserted_unverified',
        'evaluation_version': _version(evaluation_version), 'evaluator_sha256': _sha(evaluator_sha256),
        'source_condition_sha256': manifest['condition_sha256'],
        'source_snapshot_sha256': sha256_file(source / 'snapshot.json')})
    root = _inside(base, Path(base) / 'assessments' / label)
    if root.is_relative_to(source): raise ValueError('Assessment would modify source Run')
    root.mkdir(parents=True, exist_ok=False)
    _new_json(root / 'assessment.json', value)
    return value


def build_package(path, *, identity, files):
    """Explicit allowlist only; no automatic collection of logs or private assets."""
    _identity(identity)
    for name, content in files.items():
        _relative(name)
        if name == 'manifest.json' or not isinstance(content, bytes): raise ValueError('Invalid package entry')
    _reader_files(files)
    manifest = {'schema_version': SCHEMA, 'identity': identity,
        'files': {name: {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}
                  for name, content in sorted(files.items())}}
    if sum(map(len, files.values())) > MAX_PACKAGE_BYTES: raise ValueError('Package limit exceeded')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream, zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()): archive.writestr(name, content)
        archive.writestr('manifest.json', _json_bytes(manifest))
    return path


def _reader_files(files):
    if not all(name in files for name in READER_FILES) or not any(n.startswith('data/') for n in files) or not any(n.startswith('code/') for n in files):
        raise ValueError('Reader report/data/code/reproduction route required')


def restore_package(path, destination, *, expected_campaign_uuid, expected_package_sha256=None):
    """Verify whole archive before writing. External digest authenticates exact bytes.

    Passing only a campaign UUID verifies consistency, not source authenticity.
    A public download gate must also provide its trusted expected package digest.
    Never executes downloaded code.
    """
    _uuid(expected_campaign_uuid)
    if expected_package_sha256 is not None and sha256_file(path) != _sha(expected_package_sha256):
        raise ValueError('Package digest mismatch')
    destination = Path(destination)
    if destination.exists(): raise FileExistsError(destination)
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)): raise ValueError('Duplicate package path')
        # Windows is case insensitive; packages must be portable to that filesystem.
        if len(names) != len({n.casefold() for n in names}): raise ValueError('Case-alias package path')
        folded = {n.casefold() for n in names}
        if any('/'.join(n.casefold().split('/')[:i]) in folded
               for n in names for i in range(1, len(n.split('/')))):
            raise ValueError('File/directory package path conflict')
        if sum(item.file_size for item in infos) > MAX_PACKAGE_BYTES: raise ValueError('Package limit exceeded')
        for item in infos:
            _relative(item.filename)
            if item.is_dir() or stat.S_ISLNK(item.external_attr >> 16): raise ValueError('Only regular files allowed')
        if 'manifest.json' not in names: raise ValueError('Package manifest missing')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('schema_version') != SCHEMA: raise ValueError('Unknown package schema')
        identity = _identity(manifest['identity'])
        if identity['campaign_uuid'] != expected_campaign_uuid: raise ValueError('Foreign package campaign')
        records = manifest['files']
        _reader_files(records)
        if set(names) != {*records, 'manifest.json'}: raise ValueError('Package file inventory mismatch')
        contents = {name: archive.read(name) for name in names}
        for name, record in records.items():
            content = contents[name]
            if len(content) != record['bytes'] or hashlib.sha256(content).hexdigest() != _sha(record['sha256']):
                raise ValueError('Package content hash mismatch')
    destination.mkdir(parents=True, exist_ok=False)
    for name, content in contents.items():
        output = _inside(destination, destination / str(_relative(name)))
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('xb') as stream: stream.write(content)
    return manifest
