"""Descriptive, cohort-separated summaries and publication figures from analysis.

This does not change frozen extraction rules. It can be rerun on a new output
directory after acquisition; unstarted slots are retained in the slot ledger.
"""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import statistics

from research.analyze import read_json, write_json, write_csv

ARMS=('explore','preload','explained')
COLORS={'explore':'#3562A0','preload':'#C06F24','explained':'#697A32'}


def distribution(values):
    values=[v for v in values if v is not None]
    if not values:
        return {'n':0,'mean':None,'median':None,'sd':None,'min':None,'max':None,'q1':None,'q3':None}
    q=statistics.quantiles(values,n=4,method='inclusive') if len(values)>1 else [values[0]]*3
    return {'n':len(values),'mean':statistics.mean(values),'median':statistics.median(values),
            'sd':statistics.stdev(values) if len(values)>1 else None,
            'min':min(values),'max':max(values),'q1':q[0],'q3':q[2]}


def summarize(data, plan=None):
    # Saved acquisition tables are historical HTTP observations. New summaries
    # cannot silently relabel them as research quality with browser coverage.
    data = {**data, 'runs': [dict(row) for row in data['runs']]}
    for row in data['runs']:
        scoring = row.get('scoring') or {}
        if scoring.get('evaluation_version') == '1.2.0' and (
                scoring.get('research_status') != 'complete'
                or scoring.get('browser_cart_coverage') not in ('agent_observed_C-015_C-016', 'agent_assessed_C-015_C-016')):
            row['quality'] = None
            row['verdict'] = (row.get('confirmed_product_failure') or {}).get('verdict')
    groups=defaultdict(list)
    for r in data['runs']:
        groups[(r['cohort'],r['condition'])].append(r)
    stats=[]
    for (cohort,arm),runs in sorted(groups.items()):
        stat={'cohort':cohort,'condition':arm,'attempts':len(runs),
              'quality_pass':sum(r['verdict']=='pass' for r in runs),
              'quality_fail':sum(r['verdict'] in ('fail','fail_critical') for r in runs),
              'evaluation_incomplete':sum((r.get('scoring') or {}).get('research_status') != 'complete' for r in runs),
              'quality_missing':sum(r['quality'] is None for r in runs),
              'usage_complete':sum(r['usage_complete'] for r in runs),
              'execution_states':dict(Counter(r['execution']['state'] for r in runs))}
        for metric in ('input_tokens','output_tokens','total_tokens','calls','mean_input'):
            stat[metric]=distribution([r.get(metric) for r in runs])
        stat['success_only_total']=distribution([r['total_tokens'] for r in runs
                if r['verdict']=='pass' and r['execution']['state']=='completed'])
        stats.append(stat)
    primary=[r for r in data['runs'] if r['cohort']=='primary18']
    blocks=[]
    for b in range(1,7):
        runs={r['condition']:r for r in primary if r['block']==b}
        complete=set(runs)==set(ARMS) and all(r['total_tokens'] is not None for r in runs.values())
        for a,c in [('preload','explore'),('explained','explore'),('explained','preload')]:
            va=runs.get(a,{}).get('total_tokens');vc=runs.get(c,{}).get('total_tokens')
            blocks.append({'block':b,'contrast':a+' - '+c,'complete_block':complete,
                          'difference':va-vc if complete else None,
                          'ratio':va/vc if complete and vc else None,
                          'all_quality_pass':all(r['verdict']=='pass' for r in runs.values()) if complete else None})
    slots=[]
    for s in (plan or {}).get('slots',[]):
        r=next((r for r in primary if r['run_id']==s['run_id']),None)
        slots.append({**s,'status':r['execution']['state'] if r else 'not_started',
                      'quality':r['quality'] if r else None,'verdict':r['verdict'] if r else None,
                      'usage_complete':r['usage_complete'] if r else None,
                      'total_tokens':r['total_tokens'] if r else None,
                      'run_instance_id':r['run_instance_id'] if r else None})
    selected=[]
    for arm in ARMS:
        good=[r for r in primary if r['condition']==arm and r['usage_complete'] and
              r['verdict']=='pass' and r['execution']['state']=='completed']
        if good:
            median=statistics.median(r['total_tokens'] for r in good)
            chosen=min(good,key=lambda r:(abs(r['total_tokens']-median),r['started_at'],r['run_id']))
            selected.append({'condition':arm,'run_id':chosen['run_id'],'run_instance_id':chosen['run_instance_id'],
                             'root':chosen['root'],'total_tokens':chosen['total_tokens'],'arm_median':median,
                             'human_review':'not_run'})
        else:
            selected.append({'condition':arm,'run_id':None,'human_review':'no_eligible_pass_inspect_failures'})
    mechanisms=[]
    for r in data['runs']:
        calls=[c for c in data['calls'] if c['run_instance_id']==r['run_instance_id']]
        actions=[a for a in data['actions'] if a['run_instance_id']==r['run_instance_id']]
        native_source=[a for a in actions if 'source_read' in a['labels']]
        seed=[a for a in actions if 'SampleData.cs' in str(a['inputs']) and a['output_chars']>=10000]
        # Threshold describes magnitude only. It was not a frozen hypothesis cutoff.
        logs=[a for a in actions if a['tool']=='bash' and 'validation' in a['labels'] and a['output_chars']>=10000]
        mechanisms.append({'cohort':r['cohort'],'run_id':r['run_id'],'condition':r['condition'],
            'multi_tool_requests':sum(len(c.get('response_tool_ids',[]))>1 for c in calls),
            'text_only_requests':sum(not c.get('response_tool_ids') for c in calls),
            'actions_per_call':r['actions']/r['calls'] if r['calls'] else None,
            'source_action_count':len(native_source),
            'source_output_chars':sum(a['output_chars'] for a in native_source),
            'source_output_char_exposure':sum(a['subsequent_input_char_exposure'] for a in native_source),
            'large_seed_read_actions':len(seed),'large_seed_char_exposure':sum(a['subsequent_input_char_exposure'] for a in seed),
            'large_validation_output_actions':len(logs),'large_validation_char_exposure':sum(a['subsequent_input_char_exposure'] for a in logs),
            'build_error_actions':r['build_error_actions'],'test_failure_text_actions':r['test_failure_actions'],
            'revision_actions':r['action_label_counts'].get('revision',0),
            'unknown_actions':r['action_label_counts'].get('other_unknown',0),
            'initial_retention':r['initial_prompt_present_calls'],'calls':r['calls']})
    return {'groups':stats,'block_contrasts':blocks,'slots':slots,'human_review_selection':selected,
            'mechanisms':mechanisms,'note':'Descriptive only. 10,000-character bin is a post-acquisition display aid, not a frozen hypothesis criterion. Large seed candidates require SampleData.cs in the literal tool input and can miss shell-variable reads; zero is not absence of catalog delivery.'}


def figures(data, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, MaxNLocator
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,
        'axes.spines.right':False,'axes.grid':True,'grid.color':'#E5E7EB','grid.linewidth':0.6,
        'axes.axisbelow':True,'figure.facecolor':'white','savefig.facecolor':'white'})
    for cohort in sorted({r['cohort'] for r in data['runs']}):
        runs=[r for r in data['runs'] if r['cohort']==cohort]
        if not runs:
            continue
        fig,axes=plt.subplots(1,3,figsize=(14,4.5),sharey=True,layout='constrained')
        maxcall=max(r['calls'] for r in runs)
        ymax=max((c.get('input_tokens') or 0 for c in data['calls'] if c['cohort']==cohort),default=1)
        for ax,arm in zip(axes,ARMS):
            rr=sorted([r for r in runs if r['condition']==arm],key=lambda r:r['run_id'])
            for i,r in enumerate(rr):
                cc=[c for c in data['calls'] if c['run_instance_id']==r['run_instance_id'] and c.get('input_tokens') is not None]
                ax.plot([c['call_index'] for c in cc],[c['input_tokens'] for c in cc],
                        color=COLORS[arm],alpha=0.45+0.5*(i+1)/max(len(rr),1),
                        linestyle=['-','--',':','-.',(0,(5,1)),(0,(1,1))][i%6],
                        linewidth=1.5,label=r['run_id'].rsplit('-',1)[-1]+(' (no usage)' if not cc else ''))
            ax.set_title(arm+' | '+str(len(rr))+' Runs');ax.set_xlabel('Model call within Run')
            ax.set_xlim(1,max(2,maxcall));ax.set_ylim(0,ymax*1.05);ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            if not any(r['calls'] for r in rr):
                ax.text(.5,.5,'No provider usage observed',transform=ax.transAxes,ha='center',color='#555555')
            if rr:ax.legend(title='Attempt',ncol=2,frameon=False,fontsize=8)
        axes[0].set_ylabel('Provider input tokens / call')
        axes[0].yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v/1000:,.0f}k'))
        fig.suptitle(cohort+' | Input growth in every observed Run')
        fig.savefig(out/(cohort+'-input.png'),dpi=160);plt.close(fig)
        fig,axes=plt.subplots(1,3,figsize=(14,4.5),sharey=True,layout='constrained')
        ymax=max((c.get('observed_cumulative_input',0)+c.get('observed_cumulative_output',0)
                  for c in data['calls'] if c['cohort']==cohort),default=1)
        for ax,arm in zip(axes,ARMS):
            rr=sorted([r for r in runs if r['condition']==arm],key=lambda r:r['run_id'])
            for i,r in enumerate(rr):
                cc=[c for c in data['calls'] if c['run_instance_id']==r['run_instance_id']
                    and 'observed_cumulative_input' in c]
                ax.plot([c['call_index'] for c in cc],
                        [c['observed_cumulative_input']+c['observed_cumulative_output'] for c in cc],
                        color=COLORS[arm],alpha=0.45+0.5*(i+1)/max(len(rr),1),
                        linestyle=['-','--',':','-.',(0,(5,1)),(0,(1,1))][i%6],linewidth=1.5,
                        label=r['run_id'].rsplit('-',1)[-1]+(' (no usage)' if not cc else (' (partial)' if not r['usage_complete'] else '')))
            ax.set_title(arm+' | '+str(len(rr))+' Runs');ax.set_xlabel('Model call within Run')
            ax.set_xlim(1,max(2,maxcall));ax.set_ylim(0,ymax*1.05)
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            if not any(r['calls'] for r in rr):
                ax.text(.5,.5,'No provider usage observed',transform=ax.transAxes,ha='center',color='#555555')
            if rr:ax.legend(title='Attempt',ncol=2,frameon=False,fontsize=8)
        axes[0].set_ylabel('Observed cumulative input + output tokens')
        axes[0].yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v/1e6:.1f}M'))
        fig.suptitle(cohort+' | Accumulated provider usage\nPartial sums are not complete Run totals')
        fig.savefig(out/(cohort+'-cumulative.png'),dpi=160);plt.close(fig)
        fig,axes=plt.subplots(1,3,figsize=(14,4.5),sharex=True,sharey=True,layout='constrained')
        maxmean=max((r['mean_input'] or 0 for r in runs),default=1)
        for ax,arm in zip(axes,ARMS):
            rr=[r for r in runs if r['condition']==arm and r['mean_input'] is not None]
            for i,r in enumerate(rr):
                ax.scatter(r['calls'],r['mean_input'],color=COLORS[arm],s=55,
                           marker='o' if r['verdict']=='pass' else 'x')
                near=any(abs(p['calls']-r['calls'])<7 and abs(p['mean_input']-r['mean_input'])<4000 for p in rr[:i])
                ax.annotate(r['run_id'].rsplit('-',1)[-1],(r['calls'],r['mean_input']),
                            xytext=(-25,18) if near else (5,5 if i%2==0 else -12),textcoords='offset points',fontsize=8,
                            arrowprops={'arrowstyle':'-','color':'#888888','lw':0.6} if near else None)
            ax.set_xlabel('Model calls / Run');ax.set_title(arm)
            ax.set_xlim(0,max(2,maxcall)*1.16);ax.set_ylim(0,max(1,maxmean)*1.16)
            if not rr:
                ax.text(.5,.5,'No complete input total',transform=ax.transAxes,ha='center',color='#555555')
        axes[0].set_ylabel('Mean input tokens / call')
        axes[0].yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v/1000:,.0f}k'))
        fig.suptitle(cohort+' | Calls x mean input = total input\nCircle: quality pass; cross: other outcome; labels: attempt')
        fig.savefig(out/(cohort+'-decomposition.png'),dpi=160);plt.close(fig)
    primary=[r for r in data['runs'] if r['cohort']=='primary18']
    if primary:
        fig,ax=plt.subplots(figsize=(9,4.8),layout='constrained')
        for offset,arm in zip([-.12,0,.12],ARMS):
            rr=sorted([r for r in primary if r['condition']==arm and r['total_tokens'] is not None],key=lambda r:r['block'])
            for i,r in enumerate(rr):
                ax.plot(r['block']+offset,r['total_tokens'],marker='o' if r['verdict']=='pass' else 'x',
                        linestyle='none',color=COLORS[arm],label=arm if i==0 else None)
        ax.set_xlim(.5,6.5)
        ax.set_xticks(range(1,7));ax.set_ylim(bottom=0)
        ax.set_xlabel('Randomized execution block');ax.set_ylabel('Input + output tokens / Run')
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v/1e6:.1f}M'))
        ax.legend(frameon=False,ncol=3)
        ax.set_title('Primary 18 slots | All observed totals\nCircle: quality pass; cross: other outcome. Missing totals are not plotted.')
        fig.savefig(out/'primary18-totals.png',dpi=160);plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--analysis',type=Path,action='append',required=True)
    p.add_argument('--plan',type=Path)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    if args.out.exists():
        raise SystemExit('Refusing to overwrite output')
    data={'runs':[],'calls':[],'actions':[],'reads':[]}
    for source in args.analysis:
        x=read_json(source)
        for k in data:data[k].extend(x[k])
    ids=[r['run_instance_id'] for r in data['runs']]
    if len(ids)!=len(set(ids)):
        raise SystemExit('Duplicate Run instance in report inputs')
    args.out.mkdir(parents=True)
    result=summarize(data,read_json(args.plan) if args.plan else None)
    write_json(args.out/'summary.json',result)
    for name in ('groups','block_contrasts','slots','human_review_selection','mechanisms'):
        write_csv(args.out/(name+'.csv'),result[name])
    figures(data,args.out)
    print(args.out)


if __name__=='__main__':
    main()
