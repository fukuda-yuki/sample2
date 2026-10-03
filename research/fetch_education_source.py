"""Fetch the pinned public 21-file Contoso subset without credentials/config changes."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import urllib.parse
import urllib.request

from . import migration_tasks as common


def fetch(repo, destination):
    repo, destination = Path(repo).resolve(), Path(destination).resolve()
    permitted = (repo / 'artifacts').resolve()
    if not destination.is_relative_to(permitted):
        raise ValueError('New upstream snapshot must stay inside this repository artifacts/')
    pin = common.read_json(repo / 'research/tasks/contoso-enrollment/source-pin.json')
    existing = destination.exists()
    if not existing:
        destination.mkdir(parents=True)
    for relative, expected in pin['sha256'].items():
        parts = PurePosixPath(relative)
        if parts.is_absolute() or '..' in parts.parts:
            raise ValueError('Unsafe pinned source path')
        path = destination / relative
        if existing:
            payload = path.read_bytes()
        else:
            url = 'https://raw.githubusercontent.com/jbogard/ContosoUniversity/' + pin['source_commit'] + '/' + urllib.parse.quote(relative, safe='/')
            with urllib.request.urlopen(url, timeout=30) as response:
                payload = response.read(1_000_001)
            if len(payload) > 1_000_000:
                raise ValueError('Unexpected large source file')
        blob = hashlib.sha1(b'blob ' + str(len(payload)).encode() + b'\0' + payload).hexdigest()
        if hashlib.sha256(payload).hexdigest() != expected or blob != pin['git_blobs'][relative]:
            raise ValueError('Exact source commit/blob mismatch: ' + relative)
        if not existing:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
    return {'source_root': str(destination), 'source_commit': pin['source_commit'], 'verified_files': len(pin['sha256']),
            'license': pin['license'], 'status': 'exact_commit_blob_and_sha256_verified', 'credentials_used': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    print(json.dumps(fetch(args.repo, args.out or args.repo / 'artifacts/education-upstream-v1/source')))


if __name__ == '__main__':
    main()
