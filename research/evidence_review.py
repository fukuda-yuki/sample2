"""Post-acquisition evidence index. Does not change frozen action classifications."""
import argparse
from collections import Counter
from pathlib import Path

from research.analyze import read_json, write_csv, write_json


def build(data):
    rows=[]
    for run in data['runs']:
        rid=run['run_instance_id']
        calls=[c for c in data['calls'] if c['run_instance_id']==rid]
        actions=[a for a in data['actions'] if a['run_instance_id']==rid]
        increases=[]
        for c in sorted(calls,key=lambda c:c.get('input_delta') or 0,reverse=True)[:3]:
            if c.get('input_delta') is None:continue
            previous=[a for a in actions if a['call_index']==c['call_index']-1]
            increases.append({'call_index':c['call_index'],'input_delta':c['input_delta'],
                'request_id':c['request_id'],'request_ref':c['request_ref'],
                'previous_actions':[{k:a[k] for k in ('tool_call_id','tool','inputs','labels','output_chars','native_ref')}
                                    for a in previous]})
        top=sorted(actions,key=lambda a:a['subsequent_input_char_exposure'],reverse=True)[:3]
        errors=[a for a in actions if a['build_error_observed'] or a['test_failure_text']]
        root=Path(run['root'])
        evaluation_id=run['scoring'].get('evaluation_id')
        ep=root/'evaluations'/evaluation_id/'evaluation.json' if evaluation_id else None
        ev=read_json(ep) if ep and ep.exists() else {}
        rows.append({'cohort':run['cohort'],'condition':run['condition'],'run_id':run['run_id'],
            'run_instance_id':rid,'root':str(root),'calls':run['calls'],'actions':run['actions'],
            'first_input':run['first_input'],'last_input':run['last_input'],'mean_input':run['mean_input'],
            'initial_prompt_present_calls':run['initial_prompt_present_calls'],
            'initial_blocks':run['initial_blocks'],'all_initial_blocks_present_calls':run['all_initial_blocks_present_calls'],
            'disappeared_message_count':run['disappeared_message_count'],
            'action_label_counts':run['action_label_counts'],'read_kind_counts':run['read_kind_counts'],
            'multi_tool_requests':sum(len(c.get('response_tool_ids',[]))>1 for c in calls),
            'compound_actions':sum(len(a['labels'])>1 for a in actions),
            'calls_by_label_set':dict(Counter(' + '.join(c['action_labels']) for c in calls)),
            'largest_input_increases':increases,
            'top_retained_outputs':[{k:a[k] for k in ('call_index','tool_call_id','tool','inputs','output_chars',
                'subsequent_input_count','subsequent_input_char_exposure','native_ref')} for a in top],
            'error_text_review_candidates':[{k:a[k] for k in ('call_index','tool_call_id','tool','inputs','native_ref',
                'build_error_observed','test_failure_text')} for a in errors],
            'unknown_actions':[{k:a[k] for k in ('call_index','tool_call_id','tool','inputs','native_ref')}
                for a in actions if 'other_unknown' in a['labels']],
            'quality':run['quality'],'verdict':run['verdict'],
            'nonpass_requirements':[r for r in ev.get('requirements',[]) if r.get('judgement')!='pass'],
            'evaluation_ref':str(ep) if ep else None,
            'human_review':'not_run'})
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--analysis',type=Path,action='append',required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.out.exists():raise SystemExit('Refusing to overwrite evidence index')
    data={k:[] for k in ('runs','calls','actions','reads')}
    for source in a.analysis:
        value=read_json(source)
        for k in data:data[k].extend(value[k])
    rows=build(data)
    a.out.mkdir(parents=True)
    write_json(a.out/'evidence-index.json',{'timing':'post_acquisition_descriptive_index','runs':rows,
        'caveats':['Adjacent actions are associated observations, not causal token attribution.',
                   'Error-looking text requires semantic review; FAILED 0 is not a failure.',
                   'Frozen multi-label actions and indeterminate ranges are unchanged.']})
    write_csv(a.out/'run-behavior.csv',[{k:v for k,v in r.items() if k in ('cohort','condition','run_id','run_instance_id',
        'calls','actions','first_input','last_input','mean_input','initial_prompt_present_calls','initial_blocks',
        'all_initial_blocks_present_calls','disappeared_message_count','action_label_counts','read_kind_counts',
        'multi_tool_requests','compound_actions','calls_by_label_set','quality','verdict')} for r in rows])
    print({'runs':len(rows),'index':str(a.out/'evidence-index.json')})


if __name__=='__main__':
    main()
