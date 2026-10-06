"""Whitelist final environment/model metadata after verified actual200 closure.

No environment variables, credentials, network, Docker, provider or evaluator.
Paths in private evidence references are never copied to the public outputs.
"""
from pathlib import Path
import argparse,hashlib,json,platform,re,sys

def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):
 with p.open('x',encoding='utf-8',newline='\n') as f:json.dump(d,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('facts','completion','models','out'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();facts=read(a.facts);complete=read(a.completion);models=read(a.models)
 if (complete.get('kind')!='actual_completed_original100_pairs_200_runs_all_gates_and_terminated_controller'
     or complete['actual_controller_exit_code']!=0 or complete['scoped_controller_observer_and_watch_absent'] is not True
     or (complete['pairs'],complete['actual_sent_runs'],complete['completed_pair_gates'])!=(100,200,100)
     or complete['data']['sha256']!=sha(a.facts) or complete['response_model_identity']['sha256']!=sha(a.models)
     or models.get('kind')!='final_original200_response_model_identity_metadata'):
  raise ValueError('Actual completed exact200/model evidence required')
 expected={(r['run_id'],r['run_instance_id']) for r in facts['rows']}
 if len(expected)!=200 or len(models['rows'])!=200 or {(r['run_id'],r['run_instance_id']) for r in models['rows']}!=expected:
  raise ValueError('Exact model metadata cohort required')
 snapshots={}
 for fact in facts['rows']:
  root=Path(fact['original_location']);cp=root/'condition.json'
  if sha(cp)!=fact['original_sha256']['condition.json']['sha256']:raise ValueError('Frozen condition changed')
  c=read(cp);runtime=c['runtime'];lock=c['runtime_lock']
  if c['task_id']!=fact['task'] or runtime['model_id']!='deepseek-v4.1-flash':raise ValueError('Condition/model identity differs')
  if set(lock['images'])!={'worker','evaluator','gateway'} or any(not isinstance(v,str) or not re.fullmatch(r'sha256:[0-9a-f]{64}',v) for v in lock['images'].values()):
   raise ValueError('Only exact frozen image digests may enter public environment metadata')
  safe={'runtime':{k:runtime.get(k) for k in ('id','model_id','provider','opencode_version','timeout_seconds',
   'provider_timeout_seconds','model_context_tokens','model_output_tokens','concurrency')},
   'migration_environment':{k:c['environment'].get(k) for k in ('runtime','sdk','network','target_framework','packages')},
   'frozen_image_digests':lock['images'],'frozen_tool_versions':{k:lock['versions'].get(k) for k in ('dotnet','opencode')}}
  key=hashlib.sha256(json.dumps(safe,sort_keys=True).encode()).hexdigest()
  snapshots.setdefault(key,{'configuration':safe,'run_ids':[]})['run_ids'].append(fact['run_id'])
 public_models=[{k:r[k] for k in ('pair','run_id','run_instance_id','task','condition','actual_send_observed',
  'observed_response_model_ids','model_identity_state','requests_started','requests_ended')} for r in models['rows']]
 a.out.mkdir(parents=True,exist_ok=False)
 save(a.out/'public-model-identity.json',{'kind':'public_original200_reported_model_identity_v1','pairs':100,'runs':200,
  'original_bundle_sha256':complete['original_bundle']['sha256'],'completion_receipt_sha256':sha(a.completion),
  'source_model_metadata_sha256':sha(a.models),'rows':public_models,
  'limits':['Reported response metadata does not reveal provider internal execution.',
   'Unobserved response model identity remains unobserved, including provider failures.']})
 save(a.out/'environment.json',{'kind':'actual_final_all200_analysis_environment_and_frozen_worker_references_v1',
  'original_bundle_sha256':complete['original_bundle']['sha256'],'completion_receipt_sha256':sha(a.completion),
  'analysis_host':{'python_version':sys.version.split()[0],'implementation':platform.python_implementation(),
   'system':platform.system(),'release':platform.release(),'os_version':platform.version(),
   'analysis_dependencies':'Python standard library only','workflow_scope':'Windows only'},
  'frozen_worker_configurations':snapshots,'acquisition_source_HEAD':complete['HEAD'],
  'per_run_evaluator_build_and_phase':'public-dataset.json; exact evaluator SHA and phase, not version labels alone',
  'provider_requested_model':'deepseek-v4.1-flash','response_model_evidence':'data/public-model-identity.json',
  'provider_credential_read_or_values_recorded':False,'worker_reconfiguration_or_new_sampling':False,
  'scope_limits':['This environment snapshot alone is not proof of successful public offline recalculation.',
   'Worker images/private oracle/DB/runtime omitted from public derivative; full evaluator replay is separate.']})
 print(json.dumps({'runs':200,'configurations':len(snapshots),'credential_read':False,'new_sampling':False}))
if __name__=='__main__':main()
