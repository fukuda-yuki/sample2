"""Download/verify existing public data only; never execute package contents.

Windows-only workflow for the current original 100-pair cohort. Reanalysis of
summary tables needs no downloads; raw public pair derivatives are optional.
No provider credential, model call, evaluator call or replacement acquisition.
"""
from pathlib import Path, PurePosixPath
from urllib.request import urlopen, Request
from urllib.parse import urlsplit
import argparse
import hashlib
import json
import os
import stat
import zipfile


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def native(path):
    path=path.resolve()
    return Path('\\\\?\\'+str(path)) if os.name=='nt' and not str(path).startswith('\\\\?\\') else path


def safe_relative(name):
    p=PurePosixPath(name)
    reserved={'CON','PRN','AUX','NUL'}|{base+n for base in ('COM','LPT') for n in '123456789¹²³'}
    if (p.is_absolute() or not p.parts or '..' in p.parts or '\\' in name or ':' in name
        or p.as_posix()!=name or any(part.endswith((' ','.')) or part.split('.')[0].upper() in reserved for part in p.parts)):
        raise ValueError('Unsafe archive or asset path')
    return p


def download(asset, out):
    name=safe_relative(asset['name'] if 'name' in asset else 'pair.manifest.json')
    if len(name.parts)!=1:raise ValueError('Asset names must be flat')
    url=urlsplit(asset['url'])
    if (url.scheme!='https' or url.netloc!='github.com' or url.username or url.password
        or not url.path.startswith('/fukuda-yuki/sample2/releases/download/') or url.query or url.fragment):
        raise ValueError('Only bound existing sample2 public Release URLs are allowed')
    target=native(out/name.name);h=hashlib.sha256();size=0
    with urlopen(Request(asset['url'],headers={'User-Agent':'sample2-verified-public-data-reader'}),timeout=120) as response:
        with target.open('xb') as f:
            for b in iter(lambda:response.read(1024*1024),b''):
                size+=len(b)
                if size>asset['bytes']:raise ValueError('Download exceeds exact recorded bytes')
                f.write(b);h.update(b)
    if size!=asset['bytes'] or h.hexdigest()!=asset['sha256']:
        raise ValueError('Actual downloaded asset does not match the recorded size/SHA256')
    return target


def restore(package, asset_manifest, dest):
    expected=asset_manifest['file_inventory'];names=set();case_names=set()
    dest.mkdir(exist_ok=False)
    with zipfile.ZipFile(package) as z:
        for entry in z.infolist():
            if entry.is_dir():continue
            rel=safe_relative(entry.filename);name=rel.as_posix()
            if (name in names or name.casefold() in case_names or name not in expected
                or stat.S_ISLNK(entry.external_attr>>16) or entry.file_size!=expected[name]['bytes']):
                raise ValueError('Unsafe/duplicate/unexpected member or size mismatch')
            names.add(name);case_names.add(name.casefold())
            target=native(dest.joinpath(*rel.parts));target.parent.mkdir(parents=True,exist_ok=True)
            h=hashlib.sha256();size=0
            with z.open(entry) as source,target.open('xb') as f:
                for b in iter(lambda:source.read(1024*1024),b''):
                    size+=len(b)
                    if size>expected[name]['bytes']:raise ValueError('Restored member exceeds bound size')
                    f.write(b);h.update(b)
            if size!=expected[name]['bytes'] or h.hexdigest()!=expected[name]['sha256']:
                raise ValueError('Restored file hash mismatch')
        if names!=set(expected):raise ValueError('Missing exact manifest member')
    return len(names)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--catalog',type=Path,required=True)
    p.add_argument('--expected-catalog-sha256',required=True);p.add_argument('--pair',required=True,help='1..100 or all')
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if os.name!='nt':raise SystemExit('This documented workflow targets Windows; Linux adaptation is out of scope.')
    if sha(a.catalog)!=a.expected_catalog_sha256:raise ValueError('Catalogue identity mismatch')
    catalog=json.loads(a.catalog.read_bytes())
    if (catalog.get('kind')!='current_original_source_info_v5_all100_pair_release_catalog_v1'
        or catalog.get('pairs')!=100 or catalog.get('runs')!=200
        or catalog.get('bundle_sha256')!='f39b38adc6bb46d6a12a6aefc4838155e0378c5d0dd7f5727aa68fbd4fc85334'
        or len(catalog['pair_releases'])!=100
        or {x['pair'] for x in catalog['pair_releases']}!=set(range(1,101))):
        raise ValueError('Exact current full100/200 catalogue required')
    all_ids=[]
    for item in catalog['pair_releases']:
        identities=item['original_run_instances'];order=item['selected_runs_order']
        if len(identities)!=2 or len(order)!=2 or set(order)!=set(identities):raise ValueError('Exact two original ordered members per pair required')
        all_ids+=list(identities.values())
    if len(set(all_ids))!=200:raise ValueError('All original200 UUIDs must be unique')
    chosen=catalog['pair_releases'] if a.pair=='all' else [x for x in catalog['pair_releases'] if x['pair']==int(a.pair)]
    if not chosen:raise ValueError('Pair outside original cohort')
    a.out.mkdir(parents=True,exist_ok=False);receipts=[]
    for item in chosen:
        out=a.out/f"pair-{item['pair']:03d}";out.mkdir()
        mp=download(item['pair_manifest'],out);manifest=json.loads(mp.read_bytes())
        if (manifest['pair']!=item['pair'] or manifest['plan_sha256']!=catalog['bundle_sha256']
            or manifest['sha256']!=item['package_sha256']
            or manifest['selected_runs']!=item['selected_runs_order']):
            raise ValueError('Downloaded manifest is outside the bound original pair')
        metadata=item['supplementary_metadata_assets']
        if len(metadata)!=2 or {x['name'] for x in metadata}!={'public-review.json','scan.json'}:
            raise ValueError('Exact two reviewed public metadata assets required')
        metadata_paths=[download(x,out) for x in metadata]
        metadata_hashes={f.name:sha(f) for f in metadata_paths}
        if metadata_hashes['public-review.json']!=item['publication_review_sha256']:
            raise ValueError('Downloaded original public review identity mismatch')
        parts=[download(x,out) for x in item['parts']]
        package=parts[0] if len(parts)==1 else native(out/'joined-package.zip')
        if len(parts)>1:
            with package.open('xb') as f:
                for part in parts:
                    with part.open('rb') as source:
                        for b in iter(lambda:source.read(1024*1024),b''):f.write(b)
        if package.stat().st_size!=item['package_bytes'] or sha(package)!=item['package_sha256']:
            raise ValueError('Combined public package hash mismatch')
        n=restore(package,manifest,out/'restored')
        receipts.append({'pair':item['pair'],'package_sha256':item['package_sha256'],
            'manifest_sha256':sha(mp),'exact_restored_files':n,'all_sha256_match':True,
            'supplementary_metadata_sha256':metadata_hashes,
            'model_called':False,'evaluator_called':False,'contents_executed':False})
    with (a.out/'actual-download-restore-receipt.json').open('x',encoding='utf-8') as f:
        json.dump({'catalog_sha256':a.expected_catalog_sha256,'pairs':receipts},f,indent=2);f.write('\n')
    print(json.dumps({'pairs_downloaded_verified':len(receipts),'new_sampling':False,'contents_executed':False}))


if __name__=='__main__':main()
