"""Verify published analysis package and recalculate finite all200 tables offline.

Use the MANIFEST SHA256 stated in the independent Release. This runs the listed
reviewed analysis scripts only; never calls the private exporter, evaluator,
provider, Docker, Git or downloader. Output must be a new directory.
"""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,sys

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def bound(root,name):
    parts=name.split('/')
    if not name or '\\' in name or ':' in name or any(p in ('','.','..') for p in parts):raise ValueError('Unsafe manifest path')
    p=root.joinpath(*parts).resolve()
    if not p.is_relative_to(root):raise ValueError('Manifest path escapes package')
    return p
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package-root',type=Path,required=True)
    p.add_argument('--expected-manifest-sha256',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if os.name!='nt':raise SystemExit('Documented current cohort workflow is Windows-only.')
    root=a.package_root.resolve();mp=root/'MANIFEST.json'
    if sha(mp)!=a.expected_manifest_sha256:raise ValueError('Manifest differs from the published identity')
    m=json.loads(mp.read_bytes())
    if (m.get('kind')!='source_info_v5_final_analysis_public_package_v1' or m.get('pairs')!=100 or m.get('runs')!=200
        or m.get('original_bundle_sha256')!='f39b38adc6bb46d6a12a6aefc4838155e0378c5d0dd7f5727aa68fbd4fc85334'):
        raise ValueError('Exact current cohort analysis package required')
    if m.get('python_version')!=sys.version.split()[0]:raise ValueError('Use the pinned Python version for exact byte reproducibility')
    inv=m['files']
    actual={f.relative_to(root).as_posix() for f in root.rglob('*') if f.is_file() and f!=mp}
    if actual!=set(inv):raise ValueError('Package inventory differs from exact manifest')
    for name,item in inv.items():
        f=bound(root,name)
        if f.stat().st_size!=item['bytes'] or sha(f)!=item['sha256']:raise ValueError('Package file size/SHA256 mismatch: '+name)
    out=a.out.resolve()
    if out==root or out.is_relative_to(root):raise ValueError('Reproduction output must be separate from the immutable package')
    out.mkdir(parents=True,exist_ok=False)
    code=root/'code';data=root/'data/public-dataset.json';audit=root/'data/public-check-audit.json'
    commands=[
        ['offline_reanalysis.py','--data',data,'--out',out/'core'],
        ['supplementary_reanalysis.py','--data',data,'--audit',audit,'--out',out/'supplementary-results.json'],
        ['exploratory_reanalysis.py','--data',data,'--out',out/'exploratory'],
        ['write_public_tables.py','--dataset',data,'--audit',audit,'--analysis',out/'core/analysis-results.json',
         '--supplementary',out/'supplementary-results.json','--exploratory',out/'exploratory/exploratory-results.json',
         '--out',out/'tables']]
    for command in commands:
        script=code/command[0]
        if script.relative_to(root).as_posix() not in inv:raise ValueError('Analysis script not in exact verified inventory')
        subprocess.run([sys.executable,'-B','-X','utf8',str(script),*[str(x) for x in command[1:]]],cwd=code,check=True)
    expected={name.removeprefix('results/'):item for name,item in inv.items() if name.startswith('results/')}
    generated={f.relative_to(out).as_posix():f for f in out.rglob('*') if f.is_file()}
    if set(generated)!=set(expected):raise ValueError('Recalculated result inventory differs from baseline')
    for name,f in generated.items():
        if f.stat().st_size!=expected[name]['bytes'] or sha(f)!=expected[name]['sha256']:
            raise ValueError('Recalculated output differs from published baseline: '+name)
    result={'kind':'actual_public_all200_offline_recalculation_receipt_v1',
        'manifest_sha256':sha(mp),'pairs':100,'runs':200,'exact_result_files':len(generated),
        'all_recalculated_bytes_and_sha256_match':True,'python':sys.version.split()[0],
        'provider_called':False,'model_called':False,'evaluator_called':False,'new_sampling':False,
        'statistical_recalculation_is_independent_raw_quality_audit':False}
    with (out/'actual-recalculation-receipt.json').open('x',encoding='utf8') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result))
if __name__=='__main__':main()
