"""Capture sealed catalog observations without changing acquisition or its originals.

Local evidence package builder. It never dispatches or evaluates a Run.
"""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import shutil
import subprocess


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--through-block', type=int, required=True)
    ap.add_argument('--resume-capture', action='store_true')
    ap.add_argument('--include-unsealed-stopped-run', action='append', default=[],
                    help='Explicit Run ID with confirmed stop but no acquisition seal; preserve as incomplete')
    a = ap.parse_args()
    repo, out = a.repo.resolve(), a.out.resolve()
    if os.name == 'nt':
        repo, out = Path('\\\\?\\'+str(repo)), Path('\\\\?\\'+str(out))
    if (out.exists() and not a.resume_capture) or out.is_relative_to(repo/'runs') or (out/'SNAPSHOT.json').exists():
        raise ValueError('Use a new destination outside original Runs')
    out.mkdir(parents=True,exist_ok=a.resume_capture)
    captured = datetime.now(timezone.utc).isoformat()
    retained_journal=out/'runs/catalog-comparison-v2/_control/journal.jsonl'
    if retained_journal.exists():
        captured=datetime.fromtimestamp(retained_journal.stat().st_mtime,timezone.utc).isoformat()
    ctl = repo/'runs/catalog-comparison-v2/_control'
    planrel = 'research/protocols/ms1-catalog-comparison-v2-execution-20260923-r3.json'
    plan = read(repo/planrel)
    rows, excluded, pending, additions, unsealed = [], [], [], [], []
    selected = [s for s in plan['slots'] if s['block'] <= a.through_block]
    if not set(a.include_unsealed_stopped_run) <= {s['run_id'] for s in selected}:
        raise ValueError('Unsealed exception must belong to selected Runs')
    def copy(rel, expected=None, controller_snapshot=False):
        src, dst = repo/rel, out/rel
        if controller_snapshot and dst.exists():
            rows.append({'path':rel,'bytes':dst.stat().st_size,'sha256':sha(dst),'source_sha256':sha(dst),'transformation':'none'})
            return
        before = sha(src)
        if expected and before != expected:
            raise ValueError('Source differs from seal: '+rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            if sha(dst)!=before:raise ValueError('Existing partial copy differs: '+rel)
        else:shutil.copyfile(src, dst)
        if sha(dst) != before or sha(src) != before:
            raise ValueError('Source changed during copy: '+rel)
        rows.append({'path':rel, 'bytes':dst.stat().st_size, 'sha256':before,
                     'source_sha256':before, 'transformation':'none'})
    # Capture controller state first. It is allowed to append after this point.
    control_names = ['journal.jsonl','frozen-plan.json','launch-receipt.json',
                     'start-approval.json','date-revision-adoption.json']
    for name in control_names:
        copy('runs/catalog-comparison-v2/_control/'+name,controller_snapshot=True)
    journal = [json.loads(line) for line in (out/'runs/catalog-comparison-v2/_control/journal.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    dispatched = {j['case']['run_id'] for j in journal if j.get('kind')=='dispatch'}
    for s in plan['slots']:
        if s['run_id'] in dispatched and s not in selected:
            pending.append(s)
    for block in range(1, a.through_block+1):
        rel=f'runs/catalog-comparison-v2/_control/observations-pair-{block:03d}.json'
        doc=read(repo/rel)
        if doc['plan_sha256'] != sha(repo/planrel) or {r['run_id'] for r in doc['runs']} != {s['run_id'] for s in selected if s['block']==block}:
            raise ValueError('Observation identity mismatch: '+rel)
        copy(rel)
    for s in selected:
        rid=s['run_id']; relbase='runs/catalog-comparison-v2/'+rid
        sealrel='runs/catalog-comparison-v2/_control/'+rid+'.seal.json'
        if not (repo/sealrel).exists() and rid in a.include_unsealed_stopped_run:
            manifest=read(repo/relbase/'manifest.json')
            if not (manifest.get('end_reason')=='operator_stop' and manifest.get('stop_confirmed') is True
                    and manifest.get('submission_fixed') is False and manifest.get('ended_at')
                    and not (repo/relbase/'evaluations/index.jsonl').exists()):
                raise ValueError('Stopped unsealed exception contract differs: '+rid)
            before_files={p.relative_to(repo/relbase).as_posix(): {'bytes':p.stat().st_size,'sha256':sha(p)}
                          for p in (repo/relbase).rglob('*') if p.is_file()}
            copied=[]
            for rel,record in sorted(before_files.items()):
                parts=Path(rel).parts
                reason=None
                if parts[0]=='evaluation-assets' or parts[0]=='state' and rel!='state/catalog-access.json':
                    reason='Runtime binaries or private agent state; retained evidence and workspace source are separate.'
                elif rel.endswith('.lock'):
                    reason='Operational lock.'
                if reason: excluded.append({'path':relbase+'/'+rel,**record,'reason':reason})
                else:
                    copy(relbase+'/'+rel,record['sha256']);copied.append(rel)
            after_files={p.relative_to(repo/relbase).as_posix(): {'bytes':p.stat().st_size,'sha256':sha(p)}
                         for p in (repo/relbase).rglob('*') if p.is_file()}
            if before_files!=after_files:raise ValueError('Unsealed stopped files changed during capture: '+rid)
            unsealed.append({'run_id':rid,'reason':'Confirmed operator stop; no original seal, fixed submission, normalized usage or evaluation',
                'historical_seal_verified':False,'capture_time_stability_verified':True,
                'workspace_status':'Unfixed stopped workspace bytes retained without execution or evaluation',
                'retained_file_count':len(copied)})
            print('Captured incomplete stopped Run',rid,flush=True)
            continue
        seal=read(repo/sealrel)
        if not seal.get('directory_present') or not seal.get('files'):
            raise ValueError('Unsealed Run: '+rid)
        copy(sealrel)
        current_files={p.relative_to(repo/relbase).as_posix():p for p in (repo/relbase).rglob('*') if p.is_file()}
        indexraw=(repo/relbase/'evaluations/index.jsonl').read_bytes()
        indexold=seal['files']['evaluations/index.jsonl']
        if hashlib.sha256(indexraw[:indexold['bytes']]).hexdigest()!=indexold['sha256']:
            raise ValueError('Original evaluation history was not preserved: '+rid)
        index=[json.loads(line) for line in indexraw.decode('utf-8').splitlines() if line.strip()]
        recovery_dirs=[v['directory']+'/' for v in index if v['sequence']>1]
        for v in index:
            if sha(repo/relbase/v['directory']/'evaluation.json')!=v['evaluation_sha256']:
                raise ValueError('Evaluation history binding differs: '+rid)
        records=dict(seal['files'])
        for rel,p in current_files.items():
            if rel not in records:records[rel]={'bytes':p.stat().st_size,'sha256':sha(p)}
        for rel, record in sorted(records.items()):
            parts=Path(rel).parts
            reason=None
            http_database = parts[0]=='evaluation-work' and len(parts)==3 and parts[-1] in {'store.sqlite','store.sqlite-wal','store.sqlite-shm','store.sqlite-journal'}
            if parts[0] in {'evaluation-assets','evaluation-work','workspace'} and not http_database:
                reason='Runtime binaries or duplicate mutable/build workspace; frozen source and evaluation evidence retained.'
            elif parts[0]=='state' and rel!='state/catalog-access.json':
                reason='Private agent state or authentication/configuration cache; native events retained in evidence/.'
            elif rel.endswith('.lock') or rel=='archive-reference.json':
                reason='Operational lock or reference to duplicate transport archive.'
            if reason:
                excluded.append({'path':relbase+'/'+rel,**record,'reason':reason})
                continue
            if rel not in seal['files']:
                if not (any(rel.startswith(d) for d in recovery_dirs) or rel.startswith('evidence/scoring-002-')):
                    raise ValueError('Unexplained file added after seal: '+rid+':'+rel)
                additions.append({'path':relbase+'/'+rel,'status':'evaluation_recovery_file_added_after_acquisition_seal',**record})
                copy(relbase+'/'+rel,record['sha256'])
            elif rel=='evaluations/index.jsonl' and sha(repo/relbase/rel)!=record['sha256']:
                additions.append({'path':relbase+'/'+rel,'status':'evaluation_history_append_only','original_prefix':record,'current_bytes':len(indexraw),'current_sha256':sha(repo/relbase/rel)})
                copy(relbase+'/'+rel)
            else:copy(relbase+'/'+rel,record['sha256'])
        print('Captured', rid, flush=True)
    # Save controlling plans and source, not prior analytical interpretations.
    extra=set(plan.get('pinned_files',{})) | set(plan['execution']['code_hashes'])
    extra.update([planrel, 'research/protocols/ms1-catalog-comparison-v2.json',
                  'research/protocols/ms1-catalog-date-revision-20260923.json',
                  'research/protocols/ms1-catalog-comparison-v2-execution-20260922-r2.json',
                  'research/catalog_cohort_snapshot.py'])
    # Include evaluator and browser source so the recorded judgements are inspectable.
    for folder in ['inner/evaluator','inner/browser','inner/spec']:
        for p in (repo/folder).rglob('*'):
            if p.is_file() and not {'bin','obj','node_modules','__pycache__'}.intersection(p.relative_to(repo).parts):
                extra.add(p.relative_to(repo).as_posix())
    # Initial-request baselines needed for independent identity checks.
    for arm in ['compact','expanded']:
        base=Path(plan['probe'])/('MS1-001-catalog-'+arm+'-001')
        for rel in ['condition.json','state/catalog-access.json','inputs/catalog-derived/raw-first.txt','usage/raw/started.jsonl']:
            extra.add((base/rel).as_posix())
        for line in (repo/base/'usage/raw/started.jsonl').read_text(encoding='utf-8').splitlines():
            extra.add((base/'usage/raw'/json.loads(line)['request_file']).as_posix())
    for rel in sorted(extra):
        if rel not in {r['path'] for r in rows}: copy(rel)
    original_end=max(read(out/'runs/catalog-comparison-v2'/s['run_id']/'manifest.json').get('ended_at','') for s in selected)
    snap={'schema_version':1,'kind':'sealed_cohort_snapshot','captured_at_utc':captured,
          'capture_completed_at_utc':datetime.now(timezone.utc).isoformat(),
          'latest_selected_run_ended_at':original_end,'through_block':a.through_block,
          'plan_path':planrel,'plan_sha256':sha(repo/planrel), 'assigned_slots':len(plan['slots']),
          'selected_runs':[s['run_id'] for s in selected], 'dispatched_outside_snapshot':pending,
          'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
          'scope':'All recorded Runs in the selected prefix, including failures and explicitly identified stopped unsealed Runs. Other cohorts excluded.',
          'unsealed_stopped_runs':unsealed,
          'original_bytes_preserved':True,'model_called':False,'evaluator_called':False,
          'original_inventory':rows,'excluded_files':excluded,'post_seal_evaluation_history':additions}
    write(out/'SNAPSHOT.json',snap)
    print(json.dumps({k:v for k,v in snap.items() if k not in ['original_inventory','excluded_files','selected_runs','post_seal_evaluation_history']},ensure_ascii=False))


if __name__=='__main__': main()
