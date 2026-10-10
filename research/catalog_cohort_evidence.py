"""Read saved HTTP/browser captures and frozen source; no execution or rescoring."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def lines(p):return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()]


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    root=a.root.resolve()
    if os.name=='nt' and not str(root).startswith('\\\\?\\'):root=Path('\\\\?\\'+str(root))
    snap=read(root/'SNAPSHOT.json');base=root/'runs/catalog-comparison-v2'; rows=[]; hashes={}
    def bind(p):
        with p.open('rb') as f:hashes[p.relative_to(root).as_posix()]=hashlib.file_digest(f,'sha256').hexdigest()
    for rid in snap['selected_runs']:
        run=base/rid;obs=read(base/'_control'/f'observations-pair-{int(rid[-4:])-1000:03d}.json')
        r=next(v for v in obs['runs'] if v['run_id']==rid)
        if not (run/'evaluations/index.jsonl').exists():
            if rid not in {x['run_id'] for x in snap.get('unsealed_stopped_runs',[])}:
                raise ValueError('Unexplained missing evaluation: '+rid)
            rows.append({'run_id':rid,'condition':r['case']['condition'],'block':r['case']['block'],
                         'evaluation_directory':None,'evaluation_state':'not_attempted',
                         'failed_requirements':[],'blocked_requirements':[],
                         'browser_checks':[],'source_scripts_sections':[],'layouts':[],
                         'quality_unknown':True,'cart_id_unique_constraint_recorded':None})
            continue
        index=lines(run/'evaluations/index.jsonl');record=next(v for v in index if v['evaluation_id']==r['row']['scoring']['evaluation_id'])
        ep=run/record['directory'];ev=read(ep/'evaluation.json');bind(ep/'evaluation.json')
        rr={'run_id':rid,'condition':r['case']['condition'],'block':r['case']['block'],
            'evaluation_directory':ep.relative_to(root).as_posix(),'evaluation_state':r['row']['scoring']['state'],
            'failed_requirements':[q['id'] for q in ev['requirements'] if q['judgement']=='fail'],
            'blocked_requirements':[q['id'] for q in ev['requirements'] if q['judgement'] not in ['pass','fail']],
            'browser_checks':[],'source_scripts_sections':[],'layouts':[]}
        http=ep/'http-only/evaluation.json'
        if http.exists():
            bind(http);rr['http_cart_judgements']={q['id']:q['judgement'] for q in read(http)['requirements'] if q['id'] in ['R-014','R-015']}
        bc=ep/'browser-cart';receipt=bc/'receipt.json'
        if receipt.exists():
            bind(receipt);checks=lines(ep/'results.jsonl');bind(ep/'results.jsonl')
            for removal in read(receipt)['removals']:
                cid=removal['checkId'];before=read(bc/removal['before']['path'])['page'];after=read(bc/removal['after']['path'])['page'];events=read(bc/(cid+'-events.json'))
                for field in ['before','after','beforeScreenshot','afterScreenshot']:
                    p=bc/removal[field]['path'];bind(p)
                    if hashes[p.relative_to(root).as_posix()]!=removal[field]['sha256']:raise ValueError('Browser evidence hash mismatch')
                bind(bc/(cid+'-events.json'));clicked=removal.get('clickedAt')
                posts=[e for e in events if clicked and e.get('at','')>=clicked and e.get('kind')=='request' and e.get('method')=='POST' and 'RemoveFromCart' in e.get('url','')]
                scripts=re.findall(r'<script\b[^>]*>(.*?)</script>',after['html'],re.S|re.I)
                check=next(c for c in checks if c['checkId']==cid)
                rr['browser_checks'].append({'check_id':cid,'judgement':check['judgement'],'completion':removal['completion'],
                    'clicked_at':clicked,'post_requests_to_remove_after_click':len(posts),
                    'inline_scripts_reference_remove':bool(re.search(r'RemoveLink|RemoveFromCart','\n'.join(scripts))),
                    'page_errors':[e for e in events if e.get('kind') in ['pageerror','page-error']],
                    'before_rows':before['rows'],'after_rows':after['rows'],'before_total':before['totals'],'after_total':after['totals'],
                    'before_path':(bc/removal['before']['path']).relative_to(root).as_posix(),
                    'after_path':(bc/removal['after']['path']).relative_to(root).as_posix(),
                    'after_screenshot':(bc/removal['afterScreenshot']['path']).relative_to(root).as_posix(),
                    'observation':check.get('observation')})
        for p in (run/'frozen').rglob('*.cshtml'):
            text=p.read_text(encoding='utf-8-sig')
            if 'ShoppingCart' in p.as_posix() and ('RemoveLink' in text or 'RemoveFromCart' in text):
                bind(p);rr['source_scripts_sections'].append({'path':p.relative_to(root).as_posix(),'has_scripts_section':bool(re.search(r'@section\s+Scripts',text))})
            if p.name=='_Layout.cshtml':
                bind(p);rr['layouts'].append({'path':p.relative_to(root).as_posix(),'renders_scripts_section':bool(re.search(r'RenderSection(?:Async)?\(\s*[\"\x27][Ss]cripts',text))})
        log=ep/'http-only/evidence/app-process.log'
        rr['cart_id_unique_constraint_recorded']=None
        if log.exists():
            bind(log);rr['cart_id_unique_constraint_recorded']='UNIQUE constraint failed: Carts.CartId' in log.read_text(encoding='utf-8-sig')
        rows.append(rr)
    failed=[r for r in rows if any(k in r['failed_requirements'] for k in ['R-014','R-015'])]
    summary={'selected_runs':len(rows),'runs_with_browser_captures':sum(bool(r['browser_checks']) for r in rows),
             'cart_failed_runs':len(failed),'cart_failed_with_http_both_pass':sum(all(r.get('http_cart_judgements',{}).get(k)=='pass' for k in ['R-014','R-015']) for r in failed),
             'failed_browser_checks':dict(Counter(c['completion'] for r in failed for c in r['browser_checks'] if c['judgement']=='fail')),
             'cart_failure_requirements':{k:sum(k in r['failed_requirements'] for r in rows) for k in ['R-014','R-015']},
             'failed_runs_no_remove_posts':sum(all(c['post_requests_to_remove_after_click']==0 for c in r['browser_checks']) for r in failed),
             'failed_runs_no_inline_remove_reference':sum(all(not c['inline_scripts_reference_remove'] for c in r['browser_checks']) for r in failed),
             'failed_runs_page_errors':sum(any(c['page_errors'] for c in r['browser_checks']) for r in failed),
             'failed_runs_with_unrendered_scripts_section':[r['run_id'] for r in failed if any(s['has_scripts_section'] for s in r['source_scripts_sections']) and r['layouts'] and all(not x['renders_scripts_section'] for x in r['layouts'])],
             'multi_album_failure_rows':[{'run_id':r['run_id'],'unique_constraint_recorded':r['cart_id_unique_constraint_recorded']} for r in rows if 'R-016' in r['failed_requirements']]}
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps({'summary':summary,'runs':rows,'source_sha256':hashes},ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
