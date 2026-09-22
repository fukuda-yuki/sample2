"""One reviewed pair at a time: package, Release transfer, restore and cleanup.

No model or evaluator entry point. Upload is an explicit command after review;
ambiguous writes are reconciled by name, size and hash, never overwritten.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlparse
from urllib.request import urlopen
import zipfile

from outer.harness.security import child_environment
from research.catalog_allocation_review import read, sha256, write_new
from research.catalog_share import files, inventory, native, restore, safe_member, scan, verify_public

REPOSITORY = 'fukuda-yuki/sample2'
PART_BYTES = 2**30


def package(public, output, review, *, part_bytes=PART_BYTES):
    public, output = Path(public), Path(output)
    manifest = verify_public(public)
    current = inventory(public)
    decision = read(review)
    if decision.get('publication_approved') is not True or decision.get('reviewed_inventory') != current:
        raise ValueError('Publication review must cover exactly these bytes, images, licenses and exclusions')
    if not 1 <= part_bytes <= PART_BYTES:
        raise ValueError('Parts must be at most 1 GiB')
    output.mkdir(parents=True, exist_ok=False)
    scan(public, output / 'scan.json')
    if read(output / 'scan.json')['pass'] is not True:
        raise ValueError('Public copy scan failed; no upload permitted')
    archive = output / 'pair.zip'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as stream:
        for relative, source in files(public):
            safe_member(relative)
            stream.write(source, relative)
    parts = []
    if archive.stat().st_size <= part_bytes:
        parts.append({'name': archive.name, 'bytes': archive.stat().st_size, 'sha256': sha256(archive)})
    else:
        with archive.open('rb') as source:
            number = 0
            while chunk := source.read(part_bytes):
                number += 1
                part = output / f'pair.zip.part{number:04d}'
                part.write_bytes(chunk)
                parts.append({'name': part.name, 'bytes': len(chunk), 'sha256': sha256(part)})
    if len(parts) + 3 > 1000:
        raise ValueError('Release attachment limit would be exceeded')
    asset = {'kind': 'reviewed_catalog_pair_asset', 'asset': archive.name,
        'sha256': sha256(archive), 'bytes': archive.stat().st_size, 'file_inventory': current,
        'parts': parts, 'review_sha256': sha256(review), 'scan_sha256': sha256(output / 'scan.json'),
        'plan_sha256': manifest.get('plan_sha256'), 'pair': manifest.get('pair'),
        'selected_runs': manifest.get('selected_runs'), 'attachment_count': len(parts) + 3}
    write_new(output / 'pair.manifest.json', asset)
    shutil.copyfile(review, output / 'public-review.json')
    return asset


def download(url, destination):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.netloc != 'github.com' or not parsed.path.startswith('/' + REPOSITORY + '/releases/download/'):
        raise ValueError('Expected an anonymous HTTPS asset from the designated repository')
    with urlopen(url, timeout=60) as response, Path(destination).open('xb') as target:
        shutil.copyfileobj(response, target)


def offline_extract(restored, output):
    # The downloaded reader runs from the relocated corpus. No installed local
    # research module, model, evaluator or network is used by the extraction.
    script = ("import sys,runpy; from pathlib import Path; "
        "sys.path.insert(0,str(Path.cwd())); "
        "sys.addaudithook(lambda event,args: (_ for _ in ()).throw(RuntimeError('Network forbidden')) if event.startswith('socket.') else None); "
        "sys.argv=['catalog_share','extract','--root',sys.argv[2], '--out',sys.argv[1]]; "
        "runpy.run_module('research.catalog_share',run_name='__main__')")
    result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(native(output)), str(native(restored))],
        cwd=restored, env=child_environment(), capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise ValueError('Relocated offline extraction failed: ' + result.stderr[-1500:])
    return sha256(output)


def roundtrip(asset, asset_urls, workspace, *, fetch=download):
    """Download separately, verify parts/members, restore, extract with sockets denied."""
    workspace = Path(workspace).resolve()
    parts = asset.get('parts') or [{'name': asset['asset'], 'bytes': asset['bytes'], 'sha256': asset['sha256']}]
    expanded = sum(item['bytes'] for item in asset['file_inventory'].values())
    required = expanded + asset['bytes'] * (2 if len(parts) > 1 else 1)
    if shutil.disk_usage(workspace.parent).free < required:
        raise ValueError('Insufficient physical space for download/restore')
    workspace.mkdir(parents=True, exist_ok=False)
    downloaded = workspace / 'download'
    downloaded.mkdir()
    for part in parts:
        name = part['name']
        if len(safe_member(name).parts) != 1:
            raise ValueError('Unsafe asset name')
        path = downloaded / name
        fetch(asset_urls[name], path)
        if path.stat().st_size != part['bytes'] or sha256(path) != part['sha256']:
            raise ValueError('Downloaded part differs; retain evidence and stop')
    archive = downloaded / asset['asset']
    if len(parts) != 1 or parts[0]['name'] != asset['asset']:
        with archive.open('xb') as target:
            for part in parts:
                with (downloaded / part['name']).open('rb') as source:
                    shutil.copyfileobj(source, target)
    manifest_path = workspace / 'verified-asset-manifest.json'
    write_new(manifest_path, asset)
    metadata_hashes = {}
    for name, digest in (('pair.manifest.json', sha256(manifest_path)),
                         ('public-review.json', asset.get('review_sha256')),
                         ('scan.json', asset.get('scan_sha256'))):
        if name in asset_urls:
            path = downloaded / name
            fetch(asset_urls[name], path)
            if not digest or sha256(path) != digest:
                raise ValueError('Downloaded metadata differs from the reviewed package')
            metadata_hashes[name] = digest
    restored = workspace / 'restored'
    result = restore(archive, manifest_path, restored)
    extraction_hash = offline_extract(restored, workspace / 'extraction.json')
    result.update(plan_sha256=asset.get('plan_sha256'), pair=asset.get('pair'),
        selected_runs=asset.get('selected_runs'), part_hashes=parts,
        extraction_sha256=extraction_hash, extraction_sockets_blocked=True,
        metadata_hashes=metadata_hashes,
        download_urls=asset_urls, model_called=False, evaluator_called=False,
        workspace=str(workspace), cleanup_completed=False)
    write_new(workspace / 'roundtrip.json', result)
    return result


def gh(*args):
    result = subprocess.run(['gh', *args], env=child_environment(), capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError('GitHub command did not complete; reconcile remote state before retry: ' + result.stderr[-1000:])
    return result.stdout


def release(tag):
    result = subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/releases/tags/{tag}'],
        env=child_environment(), capture_output=True, text=True, timeout=60)
    if result.returncode:
        if 'HTTP 404' in result.stderr:
            return None
        raise RuntimeError('Release readback failed; no mutation attempted')
    return json.loads(result.stdout)


def publish(package_dir, tag, target_commit):
    """Explicitly invoked after exact public review; never clobber remote assets."""
    package_dir = Path(package_dir).resolve()
    if not tag.startswith('catalog-comparison-v2-pair-') or not tag.rsplit('-', 1)[-1].isdigit():
        raise ValueError('Expected the fixed cohort/pair release tag')
    asset = read(package_dir / 'pair.manifest.json')
    expected = {part['name']: part for part in asset['parts']}
    for name in ('pair.manifest.json', 'public-review.json', 'scan.json'):
        path = package_dir / name
        expected[name] = {'name': name, 'sha256': sha256(path), 'bytes': path.stat().st_size}
    if sha256(package_dir / 'public-review.json') != asset['review_sha256'] or sha256(package_dir / 'scan.json') != asset['scan_sha256']:
        raise ValueError('Review/scan changed after packaging')
    if read(package_dir / 'scan.json')['pass'] is not True:
        raise ValueError('Unaccepted public scan')
    for name, item in expected.items():
        if sha256(package_dir / name) != item['sha256']:
            raise ValueError('Local package changed')
    remote = release(tag)
    if remote is None:
        notes = package_dir / 'release-notes.md'
        intent = {'tag': tag, 'expected': expected}
        intent_path = package_dir / 'publication-intent.json'
        if intent_path.exists():
            if read(intent_path) != intent:
                raise ValueError('Prior publication intent differs')
        else:
            write_new(intent_path, intent)
        notes.write_text(f"One allocated pair, including failures and incomplete evidence.\n\n"
            f"Frozen plan SHA-256: `{asset['plan_sha256']}`. Pair: {asset['pair']}.\n\n"
            "See the manifests and bundled notices for hashes, exclusions and reproduction limits.\n",
            encoding='utf-8', newline='\n')
        gh('release', 'create', tag, '--repo', REPOSITORY, '--target', target_commit,
           '--prerelease', '--title', tag, '--notes-file', str(notes))
        remote = release(tag)
    if remote is None or remote.get('draft'):
        raise ValueError('Public release was not confirmed')
    observed = {item['name']: item for item in remote['assets']}
    if set(observed) - set(expected):
        raise ValueError('Unexpected assets in pair release; no overwrite or deletion')
    for name, item in expected.items():
        if name in observed:
            row = observed[name]
            if row['size'] != item['bytes'] or row.get('digest') != 'sha256:' + item['sha256']:
                raise ValueError('Existing remote asset differs or cannot be verified')
        else:
            gh('release', 'upload', tag, str(package_dir / name), '--repo', REPOSITORY)
    remote = release(tag)
    rows = {row['name']: row for row in remote['assets']}
    if set(rows) != set(expected) or any(rows[n].get('digest') != 'sha256:' + v['sha256'] for n, v in expected.items()):
        raise ValueError('Uploaded assets failed independent readback')
    return {name: row['browser_download_url'] for name, row in rows.items()}


def cleanup(workspace, allowed_root, receipt):
    """Only owned public copies and transfer scratch, after verified restoration."""
    workspace, allowed_root = Path(workspace).resolve(), Path(allowed_root).resolve()
    if workspace == allowed_root or not workspace.is_relative_to(allowed_root):
        raise ValueError('Cleanup must remain inside the designated staging root')
    if not receipt.get('hashes_match') or not receipt.get('extraction_sockets_blocked'):
        raise ValueError('No verified round trip')
    transfer_root = Path(receipt['workspace']).resolve()
    if not transfer_root.is_relative_to(workspace) or transfer_root == workspace:
        raise ValueError('Transfer workspace escaped the owned pair workspace')
    targets = [workspace / name for name in ('public', 'package')]
    targets += [transfer_root / name for name in ('download', 'restored')]
    for path in targets:
        if path.exists():
            if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(workspace):
                raise ValueError('Cleanup target escaped its owned workspace')
            list(files(path))  # reject junctions/symlinks before recursive deletion
    for path in targets:
        if path.exists():
            shutil.rmtree(native(path))
    return {'cleanup_completed': True, 'targets': [str(p) for p in targets],
            'free_bytes_after_cleanup': shutil.disk_usage(allowed_root).free,
            'original_runs_deleted': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=('package', 'roundtrip'))
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--review', type=Path)
    p.add_argument('--urls', type=Path)
    args = p.parse_args()
    if args.mode == 'package':
        package(args.root, args.out, args.review)
    else:
        roundtrip(read(args.root), read(args.urls), args.out)


if __name__ == '__main__':
    main()
