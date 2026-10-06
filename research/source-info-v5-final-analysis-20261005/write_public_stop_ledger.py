"""Whitelist final termination/shared STOP observations, never infer a cause.

Requires actual all200 closure. Raw HTTP fence uncertainty is retained; later
shutdown confirmation is separate. No provider/evaluator/credential access.
"""
from pathlib import Path
import argparse,hashlib,json,re

def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('facts','completion','out'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();facts=read(a.facts);complete=read(a.completion)
 if (complete.get('kind')!='actual_completed_original100_pairs_200_runs_all_gates_and_terminated_controller'
     or (complete['pairs'],complete['actual_sent_runs'],complete['completed_pair_gates'])!=(100,200,100)
     or complete['actual_controller_exit_code']!=0 or complete['data']['sha256']!=sha(a.facts)
     or complete['scoped_controller_observer_and_watch_absent'] is not True):
  raise ValueError('Actual closed exact200 cohort required')
 checks=complete.get('owned_running_checks',{})
 if set(checks)!={'sample2.run','sample2.browser-review'} or any(
     v.get('exit_code')!=0 or v.get('names')!=[] for v in checks.values()):
  raise ValueError('Actual owned running-container checks required')
 if not complete.get('monitor_shutdowns'):raise ValueError('Actual monitor shutdown references required')
 batch=Path(complete['original_private_data_location']).resolve()
 registry={r['run_id']:r for r in facts['rows']}
 if len(registry)!=200:raise ValueError('Exact unique200 original Runs required')
 fields=('run_id','run_instance_id','pair','task','condition','slot')
 def binding(b):
  r=registry.get(b.get('run_id'))
  if r is None or any(b.get(k)!=r[k] for k in fields):raise ValueError('STOP target does not match original case')
  return {k:r[k] for k in fields}
 def summary(d):
  v={}
  for k in ('phase_sha256','decided_at','decision_at','at','requested_at','http_fence_confirmed','HTTP_fence_confirmed'):
   if k in d and (d[k] is None or isinstance(d[k],(str,bool,int))):v[k]=d[k]
  reason=d.get('reason')
  v['reason']=reason if isinstance(reason,str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',reason) else None
  v['reason_unavailable_or_not_whitelisted']=reason is not None and v['reason'] is None
  return v
 run_rows=[]
 for r in facts['rows']:
  root=Path(r['original_location']).resolve()
  if root.parent!=batch or root.name!=r['run_id']:raise ValueError('Original root identity differs')
  mp=root/'manifest.json'
  if sha(mp)!=r['original_sha256']['manifest.json']['sha256']:raise ValueError('Original manifest changed')
  m=read(mp);requests=[]
  for q in sorted(root.glob('stop-request*.json')):
   if sha(q)!=r['original_sha256'][q.relative_to(root).as_posix()]['sha256']:raise ValueError('Original stop request changed')
   d=read(q)
   if d.get('run_instance_id') not in (None,r['run_instance_id']):raise ValueError('Stop-request UUID differs')
   requests.append({'original_relative_path':q.relative_to(root).as_posix(),'sha256':sha(q),'saved_summary':summary(d)})
  run_rows.append({**{k:r[k] for k in fields},'execution_state':r['saved_terminal_row']['execution']['state'],
   'original_end_reason':m.get('end_reason'),'started_at':m['started_at'],'ended_at':m['ended_at'],
   'stop_confirmed':m['stop_confirmed'],'submission_fixed':m['submission_fixed'],
   'original_manifest_sha256':sha(mp),'saved_stop_requests':requests,
   'own_product_failure_inferred_from_termination':False})
 incidents=[]
 paths=set()
 for pattern in ('*/dispatch-stop.json','*/retained-stop-*.json','*/distributed-fence-*.json'):
  paths.update((batch/'_control').glob(pattern))
 for q in sorted(paths):
  d=read(q)
  def recorded_bindings(key):
   if key not in d:return None
   if not isinstance(d[key],list):raise ValueError('Recorded STOP scope must be a list')
   return [binding(b) for b in d[key]]
  owned=recorded_bindings('owned');enrolled=recorded_bindings('bindings')
  incidents.append({'original_cohort_relative_path':q.relative_to(batch).as_posix(),'sha256':sha(q),
   'saved_summary':summary(d),'owned_field_present':'owned' in d,'explicit_owned_target_bindings':owned,
   'bindings_field_present':'bindings' in d,'explicit_enrolled_scope_bindings':enrolled,
   'saved_distributed_receipt_confirmed':d.get('receipt',{}).get('confirmed'),
   'explicit_trigger_run_id':None,'trigger_run_identification_not_established_by_this_reader':True})
 result={'kind':'public_final_original200_termination_and_saved_shared_stop_observations_v1',
  'pairs':100,'runs':200,'original_bundle_sha256':complete['original_bundle']['sha256'],
  'completion_receipt_sha256':sha(a.completion),'runs_termination':run_rows,'saved_control_incidents':incidents,
  'actual_final_monitor_stop_confirmed':True,'actual_final_owned_running_containers_absent':True,
  'limits':['This whitelist does not independently identify the triggering Run or root cause; inspect bound original/public evidence before any causal attribution.',
   'A shared stop target is not proof of its own product defect or efficiency.',
   'An unrecorded owned or bindings field is null, not an empty scope. Enrolled monitoring scope does not prove actual running ownership or the triggering Run.',
   'Final running-container absence does not assert absence of stopped containers or retained files.',
   'False/unconfirmed decision-time HTTP fence flags remain unchanged; final physical shutdown evidence is a separate fact.',
   'Pre-dispatch markers retained outside original Run/cohort control, bootstrap observations, and other recovery receipts are not enumerated by this narrow ledger.',
   'Private originals/ownership/auth retained and not published; source SHA references do not make missing original bytes publicly replayable.']}
 with a.out.open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
 print(json.dumps({'runs':200,'saved_control_incidents':len(incidents),'root_cause_inferred':False,'model_called':False}))
if __name__=='__main__':main()
