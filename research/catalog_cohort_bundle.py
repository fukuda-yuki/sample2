"""Seal, verify and restore a portable evidence ZIP. Standard library only.

The archive contains recorded evidence and deterministic data tables, not a
research interpretation. Acquisition, model execution and scoring are never run.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile


def native(path):
    p=str(Path(path).resolve())
    return Path('\\\\?\\'+p) if os.name=='nt' and not p.startswith('\\\\?\\') else Path(p)


def sha(path):
    with native(path).open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def read(path):
    return json.loads(native(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    native(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def safe(name):
    p=PurePosixPath(name)
    reserved={'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(10)],*[f'LPT{i}' for i in range(10)]}
    if not name or p.is_absolute() or '\\' in name or any(x in {'','.','..'} or ':' in x or x.endswith((' ','.')) or x.split('.')[0].upper() in reserved for x in name.split('/')):
        raise ValueError('Unsafe archive path')
    return p


def inventory(root):
    root=native(root); result={}
    for folder,dirs,names in os.walk(root,followlinks=False):
        for name in dirs+names:
            p=Path(folder)/name
            if p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()):
                raise ValueError('Links are not supported')
        for name in names:
            p=Path(folder)/name; rel=p.relative_to(root).as_posix()
            if '__pycache__' in p.parts or p.suffix=='.pyc':
                raise ValueError('Unexpected Python cache in package')
            safe(rel)
            if rel!='MANIFEST.json': result[rel]={'bytes':p.stat().st_size,'sha256':sha(p)}
    return dict(sorted(result.items()))


def seal(root):
    root=native(root)
    if (root/'MANIFEST.json').exists(): raise FileExistsError('Manifest already exists')
    files=inventory(root)
    write(root/'MANIFEST.json',{'schema_version':1,'kind':'cohort_evidence_archive','files':files})
    return {'files':len(files),'logical_bytes':sum(v['bytes'] for v in files.values())}


def verify(root):
    root=native(root); manifest=read(root/'MANIFEST.json')
    if inventory(root)!=manifest['files']: raise ValueError('File set, size or SHA-256 mismatch')
    return {'pass':True,'files_verified':len(manifest['files']),'logical_bytes':sum(v['bytes'] for v in manifest['files'].values())}


def pack(root, output):
    root=native(root); output=native(output); verify(root)
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
        for rel in [*read(root/'MANIFEST.json')['files'],'MANIFEST.json']:
            z.write(root/rel,rel)
    result={'file':output.name,'bytes':output.stat().st_size,'sha256':sha(output)}
    write(output.with_suffix('.zip.json'),result)
    output.with_suffix('.zip.sha256').write_text(result['sha256']+'  '+output.name+'\n',encoding='utf-8')
    return result


def restore(archive, output, expected_hash):
    archive=native(archive); output=native(output)
    if output.exists(): raise FileExistsError('Restore destination must not exist')
    if sha(archive)!=expected_hash: raise ValueError('Archive SHA-256 differs')
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist(); names=[i.filename for i in infos]
        if len(names)!=len(set(n.casefold() for n in names)): raise ValueError('Duplicate archive member')
        for i in infos:
            safe(i.filename)
            if stat.S_ISLNK(i.external_attr>>16): raise ValueError('Symlink refused')
        manifest=json.loads(z.read('MANIFEST.json'))
        if set(names)!=set(manifest['files'])|{'MANIFEST.json'}: raise ValueError('Unexpected archive member')
        if shutil.disk_usage(output.parent).free<sum(i.file_size for i in infos): raise ValueError('Insufficient disk space')
        # Validate every compressed member before extracting any content.
        for i in infos:
            if i.filename=='MANIFEST.json': continue
            expected=manifest['files'][i.filename]
            with z.open(i) as f: h=hashlib.file_digest(f,'sha256').hexdigest()
            if i.file_size!=expected['bytes'] or h!=expected['sha256']: raise ValueError('Member differs from manifest')
        output.mkdir()
        for i in infos:
            dest=output/i.filename; dest.parent.mkdir(parents=True,exist_ok=True)
            with z.open(i) as src,dest.open('xb') as dst: shutil.copyfileobj(src,dst)
    return verify(output)


def main():
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest='action',required=True)
    for action in ['seal','verify','pack']:
        p=sub.add_parser(action);p.add_argument('--root',type=Path,required=True)
        if action=='pack':p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('restore');p.add_argument('--archive',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--sha256',required=True)
    a=ap.parse_args()
    result=seal(a.root) if a.action=='seal' else verify(a.root) if a.action=='verify' else pack(a.root,a.out) if a.action=='pack' else restore(a.archive,a.out,a.sha256)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
