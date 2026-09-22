"""Lossless NTFS retention after a Run has stopped; original bytes stay available.

Compression occurs outside generation/evaluation timing. No prior cohort is
modified by preparation; the acceptance probe uses separately owned copies.
"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess

from outer.harness import preserve
from outer.harness.security import child_environment
from research.catalog_allocation_review import read
from research.catalog_share import inventory, native


def stored_bytes(path):
    if os.name != 'nt':
        raise ValueError('This fixed retention mode requires Windows NTFS')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    function = kernel.GetCompressedFileSizeW
    function.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    function.restype = wintypes.DWORD
    high = wintypes.DWORD()
    ctypes.set_last_error(0)
    low = function(str(native(path)), ctypes.byref(high))
    if low == 0xFFFFFFFF and ctypes.get_last_error():
        raise ctypes.WinError(ctypes.get_last_error())
    return (high.value << 32) | low


def compress_tree(root, owner):
    root, owner = Path(root).resolve(), Path(owner).resolve()
    if root == owner or not root.is_relative_to(owner) or root.is_symlink() or root.is_junction():
        raise ValueError('Compression must target an owned completed Run or package')
    before = inventory(root)
    physical_before = sum(stored_bytes(root / name) for name in before)
    result = subprocess.run(['compact.exe', '/C', '/S:' + str(native(root)), '/A', '/Q'],
        env=child_environment(), capture_output=True, timeout=180)
    after = inventory(root)
    if before != after:
        raise ValueError('Original bytes changed during lossless compression')
    if result.returncode:
        raise ValueError('NTFS compression did not complete; originals retained')
    physical_after = sum(stored_bytes(root / name) for name in before)
    return {'files': len(before), 'logical_bytes': sum(v['bytes'] for v in before.values()),
        'stored_bytes_before': physical_before, 'stored_bytes_after': physical_after,
        'content_hashes_unchanged': True}


def retain_completed(batch, run_id):
    batch = Path(batch).resolve()
    root = batch / run_id
    manifest = read(root / 'manifest.json')
    if not manifest.get('stop_confirmed') or not (manifest.get('network_cleanup') or {}).get('confirmed'):
        raise ValueError('Run must be stopped and its owned network cleaned before compression')
    reference = read(root / 'archive-reference.json')
    archive = batch / '_archive'
    package = preserve.verify(archive, reference['package_id'], reference['sha256'])
    packages = {}
    def visit(item):
        packages[item['package_id']] = item
        for ref in item['references']:
            if ref['package_id'] not in packages:
                visit(preserve.verify(archive, ref['package_id'], ref['sha256']))
    visit(package)
    results = {run_id: compress_tree(root, batch)}
    for name in packages:
        results['_archive/packages/' + name] = compress_tree(archive / 'packages' / name, batch)
    preserve.verify(archive, reference['package_id'], reference['sha256'])
    return {'method': 'NTFS compression after generation and evaluation', 'run_id': run_id,
        'original_bytes_deleted': False, 'archive_verified_after_compression': True, 'directories': results}
