"""Prepare hash-checked copies of post-exploration human-review targets."""
import argparse
import json
from pathlib import Path
import shutil

from research.analyze import read_json, sha, write_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--analysis',type=Path,required=True)
    p.add_argument('--summary',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.out.exists():raise SystemExit('Refusing to overwrite review copies or state')
    data=read_json(a.analysis)
    summary=read_json(a.summary)
    a.out.mkdir(parents=True)
    targets=[]
    files=[]
    for selection in summary['human_review_selection']:
        selected=next((r for r in data['runs'] if r['run_instance_id']==selection.get('run_instance_id')),None)
        kind='median_complete_pass'
        if selected is None:
            candidates=[r for r in data['runs'] if r['condition']==selection['condition']
                and r['cohort']=='primary18' and r['execution']['state']=='completed']
            selected=min(candidates,key=lambda r:(r['started_at'],r['run_id'])) if candidates else None
            kind='earliest_completed_failure_diagnostic'
        if selected is None:
            targets.append({**selection,'material_state':'no_completed_application','human_review':'not_run'})
            continue
        root=Path(selected['root'])
        entries=[json.loads(x) for x in (root/'evaluations/index.jsonl').read_text(encoding='utf-8-sig').splitlines()]
        evaluation=next(e for e in entries if e['evaluation_id']==selected['scoring']['evaluation_id'])
        published=Path(evaluation['work_dir'])/'publish'
        configs=list(published.glob('*.runtimeconfig.json'))
        if len(configs)!=1:
            targets.append({**selection,'run_id':selected['run_id'],'run_instance_id':selected['run_instance_id'],
                'root':selected['root'],'selection_kind':kind,'quality':selected['quality'],'verdict':selected['verdict'],
                'material_state':'published_application_unavailable','human_review':'not_run',
                'diagnostic':'Inspect fixed artifact and evaluator publish evidence; no runnable copy identified.'})
            continue
        assembly=configs[0].name.removesuffix('.runtimeconfig.json')+'.dll'
        if not (published/assembly).exists():raise RuntimeError('Entry assembly missing')
        dest=a.out/selection['condition']/'application'
        dest.mkdir(parents=True)
        for source in sorted(published.rglob('*')):
            if not source.is_file():continue
            relative=source.relative_to(published)
            target=dest/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target)
            digest=sha(source)
            if sha(target)!=digest:raise RuntimeError('Review copy hash mismatch')
            files.append({'condition':selection['condition'],'source':str(source.resolve()),
                'destination':str(target.resolve()),'sha256':digest})
        targets.append({**selection,'run_id':selected['run_id'],'run_instance_id':selected['run_instance_id'],
            'root':selected['root'],'selection_kind':kind,'quality':selected['quality'],'verdict':selected['verdict'],
            'total_tokens':selected['total_tokens'],'material_state':'prepared','entry_assembly':assembly,
            'application':str(dest.resolve()),'human_review':'not_run'})
    write_json(a.out/'review-targets.json',{'targets':targets,'selection_population':'initial18_only',
        'human_review':'not_run','automated_check':'not_run','files':files})
    print({'targets':len(targets),'files_verified':len(files),'human_review':'not_run'})


if __name__=='__main__':
    main()
