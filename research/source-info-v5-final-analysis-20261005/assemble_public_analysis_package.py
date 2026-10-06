"""Allowlisted package assembly after actual original200 acquisition closure.

Does not issue public approval, scan credentials, upload, run analyses, or touch
originals. Separate actual content/privacy/rights review remains required.
"""
from pathlib import Path
import argparse,hashlib,json,shutil,sys,zipfile

BUNDLE='f39b38adc6bb46d6a12a6aefc4838155e0378c5d0dd7f5727aa68fbd4fc85334'
SCRIPTS=('offline_reanalysis.py','quality_derivation.py','export_verified_cohort.py',
 'supplementary_reanalysis.py','exploratory_reanalysis.py','write_public_tables.py',
 'reproduce_public_analysis.py','build_public_cohort_catalog_v2.py',
 'download_verified_public_pairs.py','download_verified_public_pairs_v2.py',
 'collection_analysis_binding.py','build_consolidated_public_collection_v3.py',
 'write_public_environment.py','write_public_stop_ledger.py','assemble_public_analysis_package.py')
CORE_PARTS={'primary.json':'primary','variant-results.json':'variants','fixed-family-results.json':'fixed_family_results',
 'missing-token-scenarios.json':'prespecified_missing_token_scenarios','descriptive-strata.json':'added_descriptive_strata',
 'actual-overlap-chronology.json':'added_actual_overlap_chronology'}
TABLES=('all-100-pairs.csv','all-200-runs.csv','all-27-missing-token-scenarios.csv','all-original-required-checks.csv')
RESULT_PATHS={'core/analysis-results.json',*(f'core/{n}' for n in CORE_PARTS),
 'supplementary-results.json','exploratory/exploratory-results.json','tables/table-validation.json',*(f'tables/{n}' for n in TABLES)}
CONTRACT_SHA={'sampling-contract-ja.txt':'e0f97179cd71b36f8a16a2d50084a3f2a4fd296d4a7eec9406f61e82a4d733c9',
 'frozen-protocol.json':'d055265291721575a301fc7e44640ad2888730a0fb8427936bd239fc7ef12a25',
 'historical-contract-provenance.json':'1d6a68eabcee3d480ca80cc192cbf1809c6925061746ed143b75bea48948d854'}
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('completion','data-dir','results','code','catalog','metadata-dir','static','readme','report','out'):
  p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();complete=read(a.completion);csha=sha(a.completion)
 if (complete.get('kind')!='actual_completed_original100_pairs_200_runs_all_gates_and_terminated_controller'
     or (complete.get('pairs'),complete.get('actual_sent_runs'),complete.get('completed_pair_gates'))!=(100,200,100)
     or complete.get('actual_controller_exit_code')!=0 or complete.get('scoped_controller_observer_and_watch_absent') is not True
     or complete['original_bundle']['sha256']!=BUNDLE):raise ValueError('Actual closed original200 cohort required')
 data=read(a.data_dir/'public-dataset.json');ident=data['cohort_identity'];catalog=read(a.catalog)
 if (data.get('kind')!='public_verified_all200_reanalysis_dataset_v1'
     or data.get('synthetic_fixture_not_actual_cohort') is True
     or ident['bundle_sha256']!=BUNDLE or ident['actual_completion_sha256']!=csha
     or ident['acquisition_facts_sha256']!=complete['data']['sha256']
     or ident['public_check_audit_sha256']!=sha(a.data_dir/'public-check-audit.json')
     or catalog['bundle_sha256']!=BUNDLE or catalog['completion_receipt_sha256']!=csha):
  raise ValueError('Closed cohort/data/audit/catalog binding differs')
 expected={(x['pair'],rid,uid) for x in catalog['pair_releases'] for rid,uid in x['original_run_instances'].items()}
 if (len(expected)!=200 or len(data['runs'])!=200 or len(data['original_assignments'])!=200
     or {(r['pair'],r['run_id'],r['run_instance_id']) for r in data['runs']}!=expected
     or {(r['pair'],r['run_id'],r['run_instance_id']) for r in data['original_assignments']}!=expected):
  raise ValueError('Exact original200 identities required')
 validation=read(a.data_dir/'export-validation.json')
 if (validation.get('runs')!=200 or validation.get('pairs')!=100
     or validation['all_200_dataset_sha256']!=sha(a.data_dir/'public-dataset.json')
     or ident['exporter_source_sha256']!=sha(a.code/'export_verified_cohort.py')
     or ident['derivation_source_sha256']!=sha(a.code/'quality_derivation.py')):
  raise ValueError('Actual validated exporter/code binding differs')
 dsha=sha(a.data_dir/'public-dataset.json');asha=sha(a.data_dir/'public-check-audit.json')
 result_files=sorted(f for f in a.results.rglob('*') if f.is_file())
 if {f.relative_to(a.results).as_posix() for f in result_files}!=RESULT_PATHS:
  raise ValueError('Exact14 allowlisted result paths required')
 main_result=read(a.results/'core/analysis-results.json')
 if (main_result.get('kind')!='offline_all200_analysis' or main_result.get('input_sha256')!=dsha
     or main_result.get('analysis_source_sha256')!=sha(a.code/'offline_reanalysis.py')):
  raise ValueError('Core result/input/source binding differs')
 for name,key in CORE_PARTS.items():
  if read(a.results/'core'/name)!=main_result[key]:raise ValueError('Core result component differs')
 for name,script,kind in (('supplementary-results.json','supplementary_reanalysis.py','added_full200_descriptive_and_selection_sensitivities_v1'),
     ('exploratory/exploratory-results.json','exploratory_reanalysis.py','declared_added_exploratory_all200_views_v1')):
  v=read(a.results/name)
  if v.get('kind')!=kind or v.get('input_sha256')!=dsha or v.get('source_sha256')!=sha(a.code/script):
   raise ValueError('Supplementary/exploratory result binding differs')
  if name=='supplementary-results.json' and v.get('audit_sha256')!=asha:raise ValueError('Supplementary audit differs')
 tv=read(a.results/'tables/table-validation.json')
 expected_inputs={'public-check-audit.json':asha,'analysis-results.json':sha(a.results/'core/analysis-results.json'),
  'supplementary-results.json':sha(a.results/'supplementary-results.json'),
  'exploratory-results.json':sha(a.results/'exploratory/exploratory-results.json')}
 if (tv.get('dataset_sha256')!=dsha or tv.get('source_sha256')!=sha(a.code/'write_public_tables.py')
     or tv.get('source_outputs_sha256')!=expected_inputs or tv.get('run_rows')!=200 or tv.get('pair_rows')!=100
     or tv.get('missing_scenario_rows')!=27 or set(tv['tables'])!=set(TABLES)):
  raise ValueError('Table input/source binding differs')
 for name in TABLES:
  f=a.results/'tables'/name
  if tv['tables'][name]!={'bytes':f.stat().st_size,'sha256':sha(f)}:raise ValueError('Table bytes differ')
 metadata={'environment.json':'actual_final_all200_analysis_environment_and_frozen_worker_references_v1',
  'public-model-identity.json':'public_original200_reported_model_identity_v1',
  'public-stop-ledger.json':'public_final_original200_termination_and_saved_shared_stop_observations_v1'}
 for name,kind in metadata.items():
  v=read(a.metadata_dir/name)
  if v.get('kind')!=kind or v.get('original_bundle_sha256')!=BUNDLE or v.get('completion_receipt_sha256')!=csha:
   raise ValueError('Metadata cohort binding differs')
  if name=='environment.json':
   run_ids=[rid for cfg in v['frozen_worker_configurations'].values() for rid in cfg['run_ids']]
   if len(run_ids)!=200 or set(run_ids)!={x[1] for x in expected} or v['acquisition_source_HEAD']!=complete['HEAD']:
    raise ValueError('Environment exact original200 coverage differs')
  else:
   rows=v['rows'] if name=='public-model-identity.json' else v['runs_termination']
   if (v.get('pairs'),v.get('runs'))!=(100,200) or len(rows)!=200 or {(r['pair'],r['run_id'],r['run_instance_id']) for r in rows}!=expected:
    raise ValueError('Metadata exact original200 identities differ')
   if name=='public-model-identity.json' and v['source_model_metadata_sha256']!=complete['response_model_identity']['sha256']:
    raise ValueError('Model metadata source differs')
 for name,h in CONTRACT_SHA.items():
  if sha(a.static/name)!=h:raise ValueError('Reviewed historical contract bytes differ')
 sources={}
 for n in ('public-dataset.json','public-check-audit.json','export-validation.json'):sources['data/'+n]=a.data_dir/n
 sources['data/all-100-public-pairs-catalog.json']=a.catalog
 for n in ('public-model-identity.json','public-stop-ledger.json'):sources['data/'+n]=a.metadata_dir/n
 sources['environment.json']=a.metadata_dir/'environment.json'
 for n in SCRIPTS:sources['code/'+n]=a.code/n
 for n in ('sampling-contract-ja.txt','frozen-protocol.json','historical-contract-provenance.json'):sources['contract/'+n]=a.static/n
 sources['README-ja.md']=a.readme;sources['report/research-report-ja.md']=a.report
 for f in result_files:sources['results/'+f.relative_to(a.results).as_posix()]=f
 for name,f in sources.items():
  if not f.is_file() or f.is_symlink() or '..' in Path(name).parts:raise ValueError('Unsafe or missing allowlisted material')
 a.out.mkdir(parents=True,exist_ok=False);package=a.out/'package';package.mkdir()
 for name,f in sources.items():
  dest=package/Path(name);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dest)
  if sha(dest)!=sha(f):raise ValueError('Copy differs')
 inv={name:{'bytes':f.stat().st_size,'sha256':sha(f)} for name,f in sorted((f.relative_to(package).as_posix(),f) for f in package.rglob('*') if f.is_file())}
 manifest={'kind':'source_info_v5_final_analysis_public_package_v1','pairs':100,'runs':200,
  'original_bundle_sha256':BUNDLE,'completion_receipt_sha256':csha,'catalog_sha256':sha(a.catalog),
  'acquisition_source_commit':complete['HEAD'],'python_version':sys.version.split()[0],'windows_only':True,
  'files':inv,'public_review_performed_by_this_assembler':False,'provider_called':False,'evaluator_called':False}
 mp=package/'MANIFEST.json';mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
 zp=a.out/'analysis.zip'
 with zipfile.ZipFile(zp,'x',compression=zipfile.ZIP_DEFLATED,allowZip64=True) as z:
  for f in sorted(package.rglob('*')):
   if f.is_file():z.write(f,f.relative_to(package).as_posix())
 with zipfile.ZipFile(zp) as z:
  if set(z.namelist())!=set(inv)|{'MANIFEST.json'}:raise ValueError('ZIP inventory differs')
  for name,item in inv.items():
   raw=z.read(name)
   if len(raw)!=item['bytes'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('ZIP member differs')
 print(json.dumps({'files':len(inv),'analysis_zip_sha256':sha(zp),'analysis_manifest_sha256':sha(mp),
  'actual_public_review_or_remote_publication_performed':False,'originals_modified':False}))
if __name__=='__main__':main()
