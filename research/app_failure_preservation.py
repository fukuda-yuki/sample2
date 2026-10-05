"""Authorized preservation of saved app failures; never repairs or rescoring.

HTTP failure alone is insufficient. Unknown collector/evaluator/host causes hold.
The old exact53 handler and the original evaluator result are unchanged.
"""
from pathlib import Path
import hashlib, importlib, json, re, subprocess
from outer.harness import util
from research import next_phase

POLICY_KIND = 'authorized_original_generated_app_fault_preservation_policy_v1'
CONTRACT_KIND = 'exact_saved_generated_app_fault_pair_preservation_contract_v1'
KIND = 'retained_generated_app_fault_preservation_gate_v1'
CORE = ('research/app_failure_preservation.py', 'research/pair_execution.py',
        'research/wave_dispatch.py', 'research/wave_sharing.py', 'research/next_phase_sharing.py', 'research/wave_plan.py')


def checked(ref):
    if (not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}
            or not Path(ref['path']).is_absolute() or not next_phase.verify_reference(ref)):
        raise ValueError('App-failure preservation evidence missing or changed')
    return Path(ref['path'])


def validate_policy(ref, *, historical=False):
    policy = util.read_json(checked(ref));authority = util.read_json(checked(policy['authority']))
    original = util.read_json(checked(policy['original_bundle']))
    expected_batch = Path(policy['original_bundle']['path']).parents[2] / original['cohort']
    wanted = {c['run_id']: c['run_instance_id'] for a in original['assignments'] if a['pair'] >= 67 for c in a['cases']}
    if (policy.get('kind') != POLICY_KIND or policy.get('allowed_instances') != wanted
            or Path(policy.get('batch', '.')).resolve() != expected_batch.resolve()
            or policy.get('quality_acceptance') is not False or policy.get('rescore') is not False
            or policy.get('resend_or_refill') is not False or policy.get('other_stop_conditions_unchanged') is not True
            or authority.get('kind') != 'actual_user_exact67_and_remaining_app_failure_preservation_authority'
            or authority.get('approved_by') != 'user' or authority.get('authorized') is not True
            or authority.get('actual_transcript_evidence_received') is not True
            or authority.get('user_reply_verbatim') != 'いいよ。'
            or authority.get('original_bundle') != policy['original_bundle']
            or authority.get('allowed_instances') != wanted
            or authority.get('generated_app_saved_evidence_required') is not True
            or authority.get('unknown_evaluator_or_infrastructure_fault_excluded') is not True):
        raise ValueError('Actual narrowly scoped user app-failure authority required')
    acceptance = util.read_json(checked(policy['source_acceptance']))
    review = util.read_json(checked(acceptance['independent_review']))
    finite = util.read_json(checked(acceptance['finite_validation']))
    pins = policy['source_pins'];commit = policy['source_commit']
    if (acceptance.get('kind') != 'actual_app_failure_preservation_source_acceptance'
            or acceptance.get('passed') is not True or acceptance.get('source_commit') != commit
            or acceptance.get('source_tree') != policy['source_tree'] or acceptance.get('source_pins') != pins
            or acceptance.get('authority') != policy['authority']
            or review.get('kind') != 'independent_app_failure_preservation_source_review'
            or review.get('status') != 'passed' or review.get('reviewed_commit') != commit
            or review.get('reviewed_source_sha256') != pins
            or finite.get('passed') is not True or finite.get('source_pins') != pins
            or any(finite.get(k) != 0 for k in ('errors','failures','skipped'))
            or any(acceptance.get(k) is not False for k in ('model_called','evaluator_called','credential_read'))
            or not set(CORE) <= set(pins)):
        raise ValueError('Accepted current preservation source and finite review required')
    source = Path(__file__).resolve().parents[1]
    tree = subprocess.run(['git','rev-parse',commit+'^{tree}'],cwd=source,capture_output=True,check=True).stdout.decode().strip()
    if tree != policy['source_tree']: raise ValueError('Accepted preservation Git tree changed')
    for name in CORE:
        blob = subprocess.run(['git','cat-file','blob',commit+':'+name],cwd=source,capture_output=True,check=True).stdout
        if hashlib.sha256(blob).hexdigest() != pins[name]: raise ValueError('Accepted handler Git blob changed')
        if (not historical or name == 'research/app_failure_preservation.py') and util.sha256_file(source/name) != pins[name]:
            raise ValueError('Live handler or historical classifier version differs')
    return policy


def app_exception_evidence(root):
    """Conservative saved owned-request classifier. No process/browser/model call."""
    root = Path(root);index = util.read_lines(root/'evaluations/index.jsonl')
    if len(index) != 1 or index[0].get('sequence') != 1: raise ValueError('Only original first evaluation supported')
    record=index[0];directory=root/record['directory'];evaluation=util.read_json(directory/'evaluation.json')
    manifest=util.read_json(root/'manifest.json');row=util.read_json(root/'postprocess-receipt.json')['row']
    artifact=util.artifact_hash(root/'frozen');instance=manifest['run_instance_id']
    recorded=util.read_json(directory/'record.json');scoring=row.get('scoring',{})
    keys=('run_id','evaluation_id','sequence','scoring_state','adopted','quality','verdict','spec_sha256',
          'evaluator_sha256','evaluation_sha256','artifact_sha256_outer','browser_cart_coverage','browser_review_coverage','research_status')
    if any(recorded.get(k)!=record.get(k) for k in keys): raise ValueError('Original index and stored record differ')
    if (record.get('mismatches')!=[] or record.get('verdict')!=evaluation.get('verdict') or row.get('verdict')!=record.get('verdict')
            or record.get('spec_sha256')!=evaluation.get('specSha256')
            or record.get('research_status')!='incomplete' or evaluation.get('researchStatus')!='incomplete'
            or scoring.get('research_status')!='incomplete'
            or any(scoring.get(k)!=record.get(k) for k in ('evaluation_id','sequence','evaluator_sha256','browser_cart_coverage','browser_review_coverage'))
            or evaluation.get('quality') is not None
            or record.get('browser_cart_coverage')!=evaluation.get('browserCartCoverage', 'not_run_http_only')
            or record.get('browser_review_coverage')!=evaluation.get('browserReviewCoverage')
            or any(v in ('complete','completed') for v in (record.get('browser_cart_coverage'),record.get('browser_review_coverage')))):
        raise ValueError('Original verdict/null/partial evaluation bindings required')
    implementation=util.read_json(root/'implementation-receipt.json');snapshot=util.read_json(root/'snapshot.json')
    if (implementation.get('run_id')!=root.name or implementation.get('run_instance_id')!=instance
            or implementation.get('stop_confirmed') is not True or implementation.get('submission_fixed') is not True
            or implementation.get('collection_status')!='fixed'
            or implementation.get('collection_error_type')
            or implementation.get('snapshot_sha256')!=util.sha256_file(root/'snapshot.json')
            or implementation.get('raw')!=util.tree_hashes(root/'usage/raw')
            or snapshot.get('artifact_sha256')!=artifact or snapshot.get('artifact_state')!='fixed'):
        raise ValueError('Original implementation stop/fix/raw/snapshot baseline differs')
    if (record.get('scoring_state') != 'evaluator_fault' or record.get('adopted') is not False
            or manifest.get('run_id') != root.name or record.get('run_id') != root.name
            or record.get('evaluation_sha256') != util.sha256_file(directory/'evaluation.json')
            or record.get('evaluation_id') != evaluation.get('evaluationId')
            or record.get('quality') is not None or row.get('quality') is not None
            or row.get('scoring',{}).get('state') != 'evaluator_fault'
            or manifest.get('stop_confirmed') is not True or manifest.get('submission_fixed') is not True
            or evaluation.get('artifactSha256') != artifact or record.get('artifact_sha256_outer') != artifact
            or evaluation.get('reviewRunInstanceId') != instance
            or row.get('artifact',{}).get('artifact_sha256') != artifact
            or row.get('browser_cleanup',{}).get('confirmed') is not True
            or row.get('network_cleanup',{}).get('confirmed') is not True):
        raise ValueError('Stopped/fixed original fault/cleanup/artifact required')
    intent=util.read_json(directory/'browser-intent.json')
    cleanup=util.read_json(directory/'browser-cleanup.json')
    resources=util.read_json(directory/'browser-resources.json')
    # Intent records host binding and exact generated snapshot. Do not infer it
    # from a string anywhere in a shared log.
    if (intent.get('run_instance_id') != instance or intent.get('artifact_sha256') != artifact
            or cleanup.get('run_instance_id') != instance or cleanup.get('confirmed') is not True
            or not cleanup.get('owner') or 'sample2.browser-review='+cleanup['owner'] not in intent.get('launch_command', [])
            or resources.get('owner') != cleanup['owner'] or resources.get('run_instance_id') != instance
            or not resources.get('resources')
            or not any(r.get('name') in intent.get('launch_command', []) for r in resources['resources'] if r.get('kind')=='container')
            or intent.get('spec_sha256')!=record.get('spec_sha256')
            or (intent.get('evaluator_sha256') is not None and intent['evaluator_sha256']!=record.get('evaluator_sha256'))):
        raise ValueError('Owned browser intent identity differs')
    extra={}
    if manifest['task_id'].startswith('MS1-'):
        base=intent.get('base_url')
    else:
        request_path=directory/'browser-school/request.json';request=util.read_json(request_path)
        # Fault preservation renames attempt-1-* to evaluator_fault-001-*.
        # Commands retain the original attempt path (with doubled Windows slashes).
        commands=[s.replace('\\\\','\\') for s in intent.get('collector_command', [])]
        request_commands=[Path(s) for s in commands if s.endswith('browser-school\\request.json')]
        original_attempt=request_commands[0].parents[1] if len(request_commands)==1 else None
        mounts=[s.replace('\\\\','\\') for s in recorded.get('evaluator_command', [])]
        bound_request=(original_attempt is not None and original_attempt.parent==root/'evaluations'
            and re.fullmatch(r'attempt-1-[0-9a-f]{32}',original_attempt.name)
            and 'type=bind,source='+str(original_attempt/'http-only')+',target=/result' in mounts)
        if (request.get('runInstanceId')!=instance or request.get('artifactSha256')!=artifact
                or request.get('specSha256')!=record.get('spec_sha256')
                or not bound_request):
            raise ValueError('Owned School collector request identity differs')
        base=request.get('baseUrl');extra['collector_request']=request_path
    if not isinstance(base,str) or not re.fullmatch(r'http://127\.0\.0\.1:\d+',base):
        raise ValueError('Exact owned local app endpoint required')
    log_path=directory/'browser-server.log';log=log_path.read_text(encoding='utf-8')
    if manifest['task_id'].startswith('MS1-'):
        collector_path=directory/'browser-cart/collector-result.json';collector=util.read_json(collector_path)
        faults=collector.get('faults',[])
        urls=re.findall(r'ERR_HTTP_RESPONSE_CODE_FAILURE at (http://127\.0\.0\.1:\d+/[^\s]+)', '\n'.join(faults))
        exception='UNIQUE constraint failed: Carts.RecordId'
        frames=re.findall(r'at MvcMusicStore\.Controllers\.ShoppingCartController\.AddToCart\(Int32 id\) in /work/source/(Controllers/ShoppingCartController\.cs):line (\d+)',log)
        candidates=[url for url in urls if url==base+'/ShoppingCart/AddToCart/1']
        if (len(faults)!=1 or len(urls)!=1 or not candidates or collector.get('status') != 'evaluator_fault'
                or exception not in log or not frames):
            raise ValueError('Saved generated MusicStore DB exception/request correlation required')
        url=candidates[0]
        if not re.search(r'Request finished HTTP/1\.1 GET '+re.escape(url)+r' - 500\b',log):
            raise ValueError('Owned same app request500 not recorded')
        starts=list(re.finditer(r'Request starting HTTP/1\.1 [^\n]*',log))
        segments=[log[m.start():starts[n+1].start() if n+1<len(starts) else len(log)] for n,m in enumerate(starts)
                  if re.match(r'Request starting HTTP/1\.1 GET '+re.escape(url)+r'(?:\s|$)',m.group())]
        failed=[s for s in segments if re.search(r'Request finished HTTP/1\.1 GET '+re.escape(url)+r' - 500\b',s)]
        finishes=re.findall(r'Request finished HTTP/1\.1 GET '+re.escape(url)+r' - 500\b',log)
        if not failed or len(finishes)!=len(failed) or any(exception not in s or 'ShoppingCartController.AddToCart(Int32 id)' not in s for s in failed):
            raise ValueError('Every owned failing endpoint request must have matching app exception')
        for segment in failed:
            headers=re.findall(r'([A-Za-z0-9_.]+Exception)(?: \([^\n]*?\))?:([^\n]*)',segment)
            if (not headers or any(name not in ('Microsoft.EntityFrameworkCore.DbUpdateException','Microsoft.Data.Sqlite.SqliteException')
                    or (name=='Microsoft.Data.Sqlite.SqliteException' and (exception not in detail or 'SQLite Error 19' not in detail))
                    for name,detail in headers)):
                raise ValueError('Mixed unknown app/evaluator exception blocks preservation')
        path,line=frames[-1];lines=(root/'frozen'/path).read_text(encoding='utf-8').splitlines()
        if not (1 <= int(line) <= len(lines)) or 'SaveChanges' not in lines[int(line)-1]:
            raise ValueError('Saved application stack does not match frozen source')
        category='music_generated_cart_db_constraint'
    else:
        # School missing-view is already demonstrated in exact53. A different
        # case still needs its own generated source, request, owner and attempt.
        collector_path=directory/'browser-school/collector-receipt.json';collector=util.read_json(collector_path)
        views=re.findall(r"The view '([^']+)' was not found",log)
        events_path=directory/'browser-school/events.json';events=util.read_json(events_path);extra['browser_events']=events_path
        responses=[e.get('url','') for e in events if e.get('kind')=='response' and e.get('status')==500 and e.get('url','').startswith(base+'/')]
        urls=re.findall(r'ERR_HTTP_RESPONSE_CODE_FAILURE at (http://127\.0\.0\.1:\d+/[^\s]+)', '\n'.join(collector.get('faults',[])))
        if (len(collector.get('faults',[]))!=1 or len(urls)!=1 or len(responses)!=1 or len(set(views))!=1):
            raise ValueError('Saved generated School missing-view/request correlation required')
        url=next((u for u in responses if u in urls),None)
        if not url: raise ValueError('School collector fault and500 request differ')
        match=re.fullmatch(re.escape(base)+r'/([A-Za-z0-9_]+)/([A-Za-z0-9_]+)',url)
        if not match: raise ValueError('Only ordinary controller/action missing-view requests supported')
        controller,action=match.groups();view=views[-1];path='Controllers/'+controller+'Controller.cs'
        source=(root/'frozen'/path).read_text(encoding='utf-8')
        method=re.search(r'\[HttpGet\]\s*public\s+IActionResult\s+'+re.escape(action)+r'\([^)]*\)\s*\{\s*return View\(([^;]*)\);\s*\}',source)
        argument=method.group(1).strip() if method else None
        implicit_view=(argument=='' or (argument is not None and re.fullmatch(r'new [A-Za-z0-9_.]+\([^;]*\)',argument)))
        named_view=(argument=='"'+action+'"')
        exceptions=re.findall(r'(?:System\.[A-Za-z0-9_.]*Exception|[A-Za-z0-9_.]+Exception):[^\n]*',log)
        if (not method or view != action or (root/'frozen/Views'/controller/(view+'.cshtml')).exists()
                or (root/'frozen/Views/Shared'/(view+'.cshtml')).exists()
                or not (implicit_view or named_view)
                or not exceptions or any(not e.startswith("System.InvalidOperationException: The view '"+view+"' was not found") for e in exceptions)
                or '/Views/'+controller+'/'+view+'.cshtml' not in log
                or '/Views/Shared/'+view+'.cshtml' not in log
                or collector.get('runInstanceId') != instance or collector.get('artifactSha256') != artifact
                or collector.get('specSha256')!=record.get('spec_sha256')):
            raise ValueError('Missing view must match actual generated controller and own collector')
        exception="The view '"+view+"' was not found"
        category='school_generated_missing_view'
    refs={name:next_phase.reference(path) for name,path in {
        'manifest':root/'manifest.json','implementation':root/'implementation-receipt.json','snapshot':root/'snapshot.json','postprocess':root/'postprocess-receipt.json',
        'index':root/'evaluations/index.jsonl','record':directory/'record.json','evaluation':directory/'evaluation.json',
        'intent':directory/'browser-intent.json','resources':directory/'browser-resources.json','collector':collector_path,'app_log':log_path,
        'app_source':root/'frozen'/path,'cleanup':directory/'browser-cleanup.json','archive_reference':root/'archive-reference.json',**extra}.items()}
    return {'run_id':root.name,'run_instance_id':instance,'artifact_sha256':artifact,'category':category,
            'endpoint':url,'exception':exception,'evidence':refs,'quality':None,'quality_acceptance':False,
            'retained_scoring_state':'evaluator_fault','adopted':False,'coverage':evaluation.get('browserCartCoverage',evaluation.get('browserReviewCoverage')),
            'raw_inventory':util.tree_hashes(root/'usage/raw'),'row':row}


def attest_handler(policy_ref, phase, phase_ref, *, sole_lease_held):
    if sole_lease_held is not True: raise ValueError('Sole cohort lease required for handler attestation')
    policy=validate_policy(policy_ref);modules={}
    for name in CORE:
        path=Path(importlib.import_module(name[:-3].replace('/','.')).__file__).resolve()
        if util.sha256_file(path)!=policy['source_pins'][name]: raise ValueError('Actual imported handler differs')
        modules[name]={'path':str(path),'sha256':util.sha256_file(path)}
    path=Path(phase['batch'])/'_control'/phase['phase_id']/'actual-app-preservation-handler.json'
    value={'kind':'actual_imported_app_preservation_handler','policy':policy_ref,'source_commit':policy['source_commit'],
        'source_tree':policy['source_tree'],'actual_imported_modules':modules,'sole_cohort_lease_held':True,
        'phase_id':phase['phase_id'],'phase':phase_ref,'original_bundle':phase['original_bundle'],'model_called':False,'evaluator_called':False}
    if path.exists():
        if util.read_json(path)!=value: raise ValueError('Actual handler attestation differs')
    else: util.write_new_json(path,value)
    return next_phase.reference(path)


def ensure_contract(policy_ref, phase, current, number):
    policy=validate_policy(policy_ref);batch=Path(phase['batch'])
    if batch.resolve()!=Path(policy['batch']).resolve() or phase['original_bundle']!=policy['original_bundle']:
        raise ValueError('Preservation policy cohort differs')
    bindings=[b for b in current['dispatch'].values() if b['pair']==number]
    if len(bindings)!=2 or any(b['run_id'] not in current['results'] for b in bindings):
        raise ValueError('Two original first results required for preservation contract')
    from research import pair_execution
    faults=[]
    for binding in bindings:
        row=current['results'][binding['run_id']]['row']
        if not pair_execution._postprocess_fault(row): continue
        if policy['allowed_instances'].get(binding['run_id']) != binding['run_instance_id']:
            raise ValueError('Fault instance outside user scope')
        proof=app_exception_evidence(batch/binding['run_id'])
        if proof['row'] != row or row.get('operation_status')=='cleanup_failed': raise ValueError('Original fault row or cleanup differs')
        faults.append(proof)
    if not faults: return None
    path=batch/'_control'/phase['phase_id']/('app-failure-preservation-'+str(number)+'.json')
    contract={'kind':CONTRACT_KIND,'pair':number,'policy':policy_ref,
        'phase_sha256':bindings[0]['phase_sha256'],'original_bundle':phase['original_bundle'],
        'run_instances':{b['run_id']:b['run_instance_id'] for b in bindings},'faults':faults,'quality_acceptance':False,
        'handler_execution':next_phase.reference(batch/'_control'/phase['phase_id']/'actual-app-preservation-handler.json')}
    if path.exists():
        if util.read_json(path)!=contract: raise ValueError('Immutable app-failure contract changed')
    else: util.write_new_json(path,contract)
    return next_phase.reference(path)


def validate_contract(ref, *, current=None, historical=False):
    contract=util.read_json(checked(ref));policy=validate_policy(contract['policy'],historical=historical)
    if contract.get('kind')!=CONTRACT_KIND or contract.get('quality_acceptance') is not False or not contract.get('faults'):
        raise ValueError('Typed retained app-failure contract required')
    handler=util.read_json(checked(contract['handler_execution']))
    handler_phase=util.read_json(checked(handler['phase']))
    if (handler.get('kind')!='actual_imported_app_preservation_handler' or handler.get('policy')!=contract['policy']
            or handler.get('source_commit')!=policy['source_commit'] or handler.get('source_tree')!=policy['source_tree']
            or handler.get('sole_cohort_lease_held') is not True or handler.get('original_bundle')!=contract['original_bundle']
            or handler.get('phase',{}).get('sha256')!=contract['phase_sha256']
            or not next_phase.verify_reference(handler.get('phase',{}))
            or handler.get('phase_id')!=handler_phase.get('phase_id')
            or Path(handler_phase['batch']).resolve()!=Path(policy['batch']).resolve()
            or handler_phase.get('original_bundle')!=policy['original_bundle']
            or any(handler.get(k) is not False for k in ('model_called','evaluator_called'))
            or set(handler.get('actual_imported_modules',{}))!=set(CORE)
            or any(handler['actual_imported_modules'][n].get('sha256')!=policy['source_pins'][n] for n in CORE)):
        raise ValueError('Actual accepted handler attestation required')
    original=util.read_json(checked(policy['original_bundle']));assignment=next(a for a in original['assignments'] if a['pair']==contract['pair'])
    if contract['original_bundle']!=policy['original_bundle'] or contract['run_instances']!={c['run_id']:c['run_instance_id'] for c in assignment['cases']}:
        raise ValueError('Original pair identity changed')
    ids=[f['run_id'] for f in contract['faults']]
    if len(ids)!=len(set(ids)) or not set(ids)<=set(contract['run_instances']): raise ValueError('Duplicate or foreign-pair fault')
    if current is not None:
        from research import pair_execution
        expected={rid for rid in contract['run_instances'] if pair_execution._postprocess_fault(current['results'][rid]['row'])}
        if set(ids)!=expected: raise ValueError('All and only this pair faults must be covered')
    for saved in contract['faults']:
        if policy['allowed_instances'].get(saved['run_id'])!=saved['run_instance_id']: raise ValueError('Unauthorized fault instance')
        root=Path(saved['evidence']['manifest']['path']).parent
        if root.resolve()!=(Path(policy['batch'])/saved['run_id']).resolve(): raise ValueError('Foreign original Run evidence')
        if any(not next_phase.verify_reference(r) for r in saved['evidence'].values()) or app_exception_evidence(root)!=saved:
            raise ValueError('Original app-failure evidence changed')
        post=util.read_json(checked(saved['evidence']['postprocess']))
        if post.get('phase_sha256')!=contract['phase_sha256'] or post.get('plan_sha256')!=policy['original_bundle']['sha256']:
            raise ValueError('Original fault phase/bundle differs')
        if current is not None and current['results'][saved['run_id']]['row']!=saved['row']: raise ValueError('Retained result changed')
    return contract


def gate_fields(ref):
    c=validate_contract(ref)
    return {'gate_kind':KIND,'preservation_contract':ref,'quality_acceptance':False,'retained_scoring_state':'evaluator_fault',
        'recovery_source_commit':validate_policy(c['policy'])['source_commit']}


def public_disclosure(ref):
    c=validate_contract(ref)
    return {'kind':KIND,'pair':c['pair'],'contract_sha256':ref['sha256'],'retained_scoring_state':'evaluator_fault',
        'quality':None,'quality_acceptance':False,'browser_coverage_completed':False,
        'meaning':'Saved generated app exception interrupted first evaluation. Original fault/null/partial coverage retained; preservation/publication only, no quality acceptance or rescore.'}


def validate_gate(value,current,number):
    from research import pair_execution
    c=validate_contract(value['preservation_contract'],current=current,historical=True)
    if (value.get('gate_kind')!=KIND or c['pair']!=number or value.get('phase_sha256')!=c['phase_sha256']
            or value.get('run_instances')!=c['run_instances'] or value.get('quality_acceptance') is not False
            or value.get('retained_scoring_state')!='evaluator_fault'
            or value.get('recovery_source_commit')!=validate_policy(c['policy'],historical=True)['source_commit']
            or value.get('evidence_files',{}).get(value['preservation_contract']['path'])!=value['preservation_contract']['sha256']):
        raise ValueError('Typed app-failure preservation gate binding differs')
    covered={f['run_id'] for f in c['faults']}
    if any(pair_execution._postprocess_fault(current['results'][rid]['row']) and rid not in covered for rid in c['run_instances']):
        raise ValueError('Uncovered operational/evaluator fault blocks gate')
    pair_execution._validate_gate_common(value,current,number)
