"""Verify and reproduce six public exploratory results offline (Python stdlib only)."""
import argparse, hashlib, json, subprocess, sys
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone

def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p): return json.loads(p.read_text(encoding='utf-8'))
def now(): return datetime.now(timezone.utc).isoformat()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--package', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--manifest-sha256', required=True)
    a=ap.parse_args(); root=a.package.resolve(); out=a.out.resolve(); start=now()
    if out.exists(): raise FileExistsError('Output directory must be new')
    if root==out or root in out.parents: raise ValueError('Output must be outside the package')
    manifest=root/'MANIFEST.json'
    if digest(manifest)!=a.manifest_sha256: raise ValueError('Manifest SHA mismatch')
    m=load(manifest); expected=set()
    for f in m['files']:
        rel=PurePosixPath(f['path'])
        if rel.is_absolute() or '..' in rel.parts or '\\' in f['path'] or ':' in f['path']: raise ValueError('Unsafe manifest path')
        p=root.joinpath(*rel.parts)
        if p.is_symlink() or not p.is_file() or p.stat().st_size!=f['bytes'] or digest(p)!=f['sha256']: raise ValueError('Input hash mismatch: '+f['path'])
        if f['path'] in expected: raise ValueError('Duplicate manifest path')
        expected.add(f['path'])
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual!=expected|{'MANIFEST.json'}: raise ValueError('Unexpected/missing package file')
    out.mkdir(parents=True)
    scripts=['round1_frontiers.py','round2_continuity.py','round3_measurement.py','round4_selection.py','round5_support.py','round6_stops.py']
    checks=[]
    for n,name in enumerate(scripts,1):
        target=out/f'{n:02}'
        cmd=[sys.executable,'-B','-X','utf8',str(root/'code'/name),'--data',str(root/'data'),'--out',str(target)]
        if n==2: cmd+=['--prior',str(root/'prior')]
        if n==6: cmd+=['--stop',str(root/'data'/'public-stop-origin-summary.json')]
        r=subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        (out/f'{n:02}-stdout.txt').write_bytes(r.stdout)
        (out/f'{n:02}-stderr.txt').write_bytes(r.stderr)
        if r.returncode: raise RuntimeError('Analysis failed: '+name)
        expected_result=root/'results'/f'{n:02}'/'result.json'
        if (target/'result.json').read_bytes()!=expected_result.read_bytes(): raise ValueError('Result bytes differ: '+name)
        checks.append({'stage':n,'script':name,'exit_code':r.returncode,'byte_identical':True,'result_sha256':digest(expected_result)})
    original=load(root/'history'/'02'/'result.json'); normalized=load(root/'results'/'02'/'result.json')
    old_inventory=original.pop('inputs_sha256'); new_inventory=normalized.pop('inputs_sha256')
    if original!=normalized: raise ValueError('R2 analysis content changed')
    if any(old_inventory.get(k)!=v for k,v in new_inventory.items()): raise ValueError('R2 public inventory is not an unchanged subset')
    receipt={'started_at_utc':start,'completed_at_utc':now(),'manifest_sha256':a.manifest_sha256,'manifest_files_verified':len(expected),'results':checks,
      'historical_r2_content_unchanged_except_input_inventory':True,'historical_r2_inventory_files':len(old_inventory),'public_r2_inventory_files':len(new_inventory),
      'new_model_calls':0,'evaluator_runs':0,'network_requests':0,'original_data_or_scores_changed':False,'new_research_iterations':0,
      'scope':'Offline public derived numerical reproduction; not raw stop-origin extraction, original evaluator replay, or full independent semantic quality audit.'}
    (out/'actual-recalculation-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False))

if __name__=='__main__': main()
