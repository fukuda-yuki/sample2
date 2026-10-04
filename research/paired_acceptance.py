"""Validate original finite v5 live evidence; never dispatch or read a key."""
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from outer.harness import live_usage, machine, profiles, util
from research import catalog_delivery, pair_execution


def read_reference(record):
    path=Path(record['path'])
    if util.sha256_file(path)!=record['sha256']: raise ValueError('Technical original reference changed')
    return util.read_json(path)


def utc(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.utcoffset() is None or result.utcoffset().total_seconds()!=0:
        raise ValueError('Technical timing requires UTC')
    return result


def actual_remote(gate):
    publication=util.read_json(gate['publication_receipt'])
    restored=util.read_json(gate['roundtrip_receipt'])
    if publication.get('transport_mode')!='github-release-anonymous-download-v1':
        raise ValueError('Injected transport cannot establish live acceptance')
    reference=publication['actual_remote_readback']
    if gate['evidence_files'].get(reference['path'])!=reference['sha256']:
        raise ValueError('Actual remote readback is not retained in the gate')
    remote=read_reference(reference)
    asset=publication['asset_manifest']
    expected={p['name']:(p['sha256'],p['bytes']) for p in asset['parts']}
    expected.update({'pair.manifest.json':(restored['metadata_hashes']['pair.manifest.json'],None),
        'public-review.json':(asset['review_sha256'],None),'scan.json':(asset['scan_sha256'],None)})
    rows={r['name']:r for r in remote['assets']}
    urls=publication['urls']
    if set(rows)!=set(expected) or set(urls)!=set(expected) or restored['download_urls']!=urls:
        raise ValueError('Remote/download asset inventories differ')
    prefix='/'+catalog_delivery.REPOSITORY+'/releases/download/'+remote['tag_name']+'/'
    for name,(digest,size) in expected.items():
        row=rows[name]; parsed=urlparse(urls[name])
        if (row['digest']!='sha256:'+digest or size is not None and row['size']!=size
                or row['browser_download_url']!=urls[name] or parsed.scheme!='https'
                or parsed.netloc!='github.com' or parsed.path!=prefix+name):
            raise ValueError('Actual remote asset hash/URL differs from reviewed bytes')
    return True


def resources(record,bundle_digest,pair,windows,worker_names):
    path=Path(record['path'])
    if util.sha256_file(path)!=record['sha256']: raise ValueError('Resource samples changed')
    samples,errors=live_usage.journal(path)
    if errors or not samples: raise ValueError('Resource observations missing or damaged')
    covered=set()
    for sample in samples:
        if (sample.get('pair')!=pair or sample.get('bundle_sha256')!=bundle_digest
                or sample.get('exit_code')!=0 or sample.get('error_present') is not False):
            raise ValueError('Resource monitor failed or wrong block')
        stamp=utc(sample['at'])
        rows={r['Name']:r for r in sample['samples']}
        owners=sample['owners']
        if not owners or set(rows)!={o['name'] for o in owners}:
            raise ValueError('Resource owner inventory incomplete')
        for owner in owners:
            instance=owner['run_instance_id']; name=owner['name']
            if instance not in windows or worker_names[instance]!=name:
                raise ValueError('Resource sample belongs to another instance')
            if not all(k in rows[name] for k in ('CPUPerc','MemUsage','BlockIO','NetIO')):
                raise ValueError('CPU/memory/I/O coverage incomplete')
            if windows[instance][0]<=stamp<=windows[instance][1]: covered.add(instance)
    if covered!=set(windows): raise ValueError('Each actual Run needs resource coverage')


def validate(comparison,plan,scopes):
    from research import next_phase
    execution=scopes.get('execution_evidence',{})
    if not execution.get('research/technical_pair_comparison.py'):
        raise ValueError('The dedicated v5 live comparison driver is not implemented and bound')
    if (comparison.get('kind')!='paired_execution_acceptance_v5'
            or comparison.get('plan_sha256')!=scopes['research_lead_review'].get(next_phase.V5_PLAN)
            or comparison.get('execution_asset_hashes')!=execution
            or comparison.get('maximum_dispatches')!=4 or comparison.get('research_runs_included') is not False):
        raise ValueError('Technical comparison does not bind current v5 scope')
    reference=comparison['fixed_comparison_plan']
    fixed=read_reference(reference)
    limits={'maximum_dispatches':4,'run_seconds':1800,'provider_timeout_seconds':600,
        'maximum_accumulated_run_seconds':7200,'gateway_started_calls_stop':600,
        'reported_observed_tokens_stop':20_000_000}
    if fixed.get('comparison_version') in ('go30m-20261004','go30m-guardianfix-20261004'):
        from research.technical_pair_comparison import verify_additional_authorization,verify_unsent_guardian_failure
        verify_additional_authorization(fixed['additional_authorization'])
        if fixed.get('comparison_version') == 'go30m-guardianfix-20261004':
            verify_unsent_guardian_failure(fixed['preparation_failure'])
        if fixed.get('total_actual_dispatch_upper_bound_across_plans') != 8:
            raise ValueError('Additional technical cumulative bound changed')
        limits.update(reported_observed_tokens_stop=30_000_000, comparison_wall_clock_stop_seconds=9000)
    if (any(type(fixed.get(k)) is not int or fixed[k]!=v for k,v in limits.items())
            or fixed.get('order')!=[1,2] or fixed.get('no_retries_or_replacements') is not True
            or fixed.get('settings')!=plan['settings'] or fixed.get('execution_asset_hashes')!=execution
            or fixed['plan_reference']['sha256']!=comparison['plan_sha256']):
        raise ValueError('Finite technical settings/limits/order not predeclared')
    if read_reference(fixed['plan_reference'])!=plan: raise ValueError('Technical scientific plan differs')
    created=utc(fixed['created_at'])
    assigned={c['run_id']:c for p in fixed['assignments'] for c in p['cases']}
    research_instances={c['run_instance_id'] for p in next_phase.assignments(plan) for c in p['cases']}
    if (len(fixed['assignments'])!=2 or len(assigned)!=4 or
            len({c['slot'] for c in assigned.values()})!=4 or
            len({c['run_instance_id'] for c in assigned.values()})!=4 or
            any(c['run_instance_id'] in research_instances for c in assigned.values())):
        raise ValueError('Exactly four distinct separate technical slots/instances required')
    blocks=comparison.get('blocks',[])
    if len(blocks)!=2 or [(b.get('pair'),b.get('concurrency')) for b in blocks]!=[(1,1),(2,2)]:
        raise ValueError('Exactly one serial pair followed by one concurrent pair required')
    durations=[]; intervals=[]; seen=set(); calls_total=tokens_total=0; run_seconds=0
    measured_blocks=[]
    journal_identity=None
    for block in blocks:
        bundle=read_reference(block['technical_bundle']); digest=block['technical_bundle']['sha256']
        if (bundle.get('kind')!='continuity_sharing_technical_fixture'
                or not bundle['cohort'].startswith('runs/_technical-sharing-')
                or bundle['plan']!=plan or bundle['technical_plan']!=reference
                or bundle['assignments']!=fixed['assignments'] or bundle['source_commit']!=fixed['source_commit']):
            raise ValueError('Technical bundle is not separate/settings-identical and plan-bound')
        if next_phase.acceptance_scopes(bundle['pinned_files'],plan)['execution_evidence']!=execution:
            raise ValueError('Technical code pins differ from final execution scope')
        journal=Path(block['journal']['path'])
        if util.sha256_file(journal)!=block['journal']['sha256']: raise ValueError('Technical journal changed')
        identity=(str(journal.resolve()),block['journal']['sha256'])
        if journal_identity is None: journal_identity=identity
        elif journal_identity!=identity: raise ValueError('One fixed four-slot technical journal required')
        current=pair_execution.state(journal)
        if set(current['reserved'])!=set(assigned) or set(current['dispatch'])!=set(assigned):
            raise ValueError('Extra or missing technical reservation/dispatch')
        for rid,binding in current['reserved'].items():
            if any(binding.get(k)!=v for k,v in assigned[rid].items()):
                raise ValueError('Technical assignment/instance changed')
        control=journal.parent
        if (control/'safety-stop.json').exists(): raise ValueError('Technical safety/monitor fault retained')
        if fixed.get('comparison_version') in ('go30m-20261004','go30m-guardianfix-20261004'):
            started=util.read_json(control/'wall-guardian-start.json')
            completed_guard=util.read_json(control/'wall-guardian-completed.json')
            supervisor=util.read_json(control/'wall-supervisor-completed.json')
            if (started.get('bundle_sha256')!=digest or completed_guard.get('bundle_sha256')!=digest
                    or completed_guard.get('all_gates_within_wall_limit') is not True
                    or not started.get('guardian_id')
                    or started.get('guardian_id')!=completed_guard.get('guardian_id')
                    or started.get('pid')!=completed_guard.get('pid')
                    or started.get('technical_plan_sha256')!=reference['sha256']
                    or completed_guard.get('technical_plan_sha256')!=reference['sha256']
                    or supervisor.get('bundle_sha256')!=digest
                    or supervisor.get('child_pid')!=started.get('pid')
                    or supervisor.get('child_returncode')!=0
                    or supervisor.get('guardian_completion')!=next_phase.reference(control/'wall-guardian-completed.json')):
                raise ValueError('Wall guardian completion not established')
            heartbeat_ref=completed_guard['heartbeat_journal']
            if not next_phase.verify_reference(heartbeat_ref):
                raise ValueError('Guardian heartbeat journal changed')
            heartbeats,heartbeat_errors=live_usage.journal(heartbeat_ref['path'])
            if (heartbeat_errors or not heartbeats or any(
                    h.get('sequence')!=i or h.get('guardian_id')!=started['guardian_id']
                    or h.get('pid')!=started['pid'] or h.get('bundle_sha256')!=digest
                    or h.get('technical_plan_sha256')!=reference['sha256']
                    for i,h in enumerate(heartbeats))):
                raise ValueError('Guardian heartbeat identities/sequence incomplete')
            if any(not 0<=(utc(b['at'])-utc(a['at'])).total_seconds()<=5
                   for a,b in zip(heartbeats,heartbeats[1:])):
                raise ValueError('Guardian heartbeat coverage gap')
            first_start=utc(util.read_json(control/'execute-start-1.json')['at'])
            last_gate=utc(current['gates'][2]['at'])
            if (not utc(heartbeats[0]['at'])<=first_start<=utc(heartbeats[-1]['at'])
                    or abs((utc(heartbeats[-1]['at'])-last_gate).total_seconds())>5
                    or not last_gate<=utc(completed_guard['at'])<=utc(supervisor['at'])):
                raise ValueError('Guardian does not cover the full comparison/gate period')
        number=block['pair']; bindings=[b for b in current['dispatch'].values() if b['pair']==number]
        if len(bindings)!=2 or number not in current['gates']: raise ValueError('Both real terminal Runs and gate required')
        saved_gate=current['gates'][number]; gate=util.read_json(saved_gate['receipt'])
        pair_execution._validate_gate(gate,current,number)
        actual_remote(gate)
        reserved=[e for e in pair_execution.events(journal) if e['kind']=='pair_reserved' and e['pair']==number]
        if len(reserved)!=1 or reserved[0]['concurrency']!=block['concurrency']:
            raise ValueError('Actual technical concurrency differs from fixed order')
        timing=read_reference(block['execute_start'])
        if (timing.get('pair')!=number or timing.get('bundle_sha256')!=digest
                or timing.get('technical_plan_sha256')!=reference['sha256']):
            raise ValueError('Execution start is not bound to predeclared technical plan')
        start,end=utc(timing['at']),utc(saved_gate['at'])
        completed=read_reference(block['normal_completion'])
        if (completed.get('pair')!=number or completed.get('bundle_sha256')!=digest
                or completed.get('technical_plan_sha256')!=reference['sha256']
                or (completed.get('result') or {}).get('reason')!='pair_publication_restore_cleanup_required'
                or not start<=utc(completed['at'])<=end):
            raise ValueError('Technical block did not complete without a campaign fault')
        duration=(end-start).total_seconds()
        if not created<=start<end or duration!=block.get('total_elapsed_seconds'):
            raise ValueError('Total time must start after freeze and end after actual cleanup gate')
        intervals.append((start,end)); durations.append(duration)
        windows={}; names={}; http={}; run_measurements=[]
        for binding in bindings:
            rid=binding['run_id']; instance=binding['run_instance_id']; root=journal.parents[1]/rid
            if rid in seen: raise ValueError('Technical Run counted twice')
            seen.add(rid)
            if binding['plan_sha256']!=digest: raise ValueError('Technical dispatch belongs to another bundle')
            implementation=current['implementations'].get(rid,{}).get('receipt',{})
            if (implementation.get('stop_confirmed') is not True or implementation.get('error_type')
                    or implementation.get('raw')!=util.tree_hashes(root/'usage/raw')):
                raise ValueError('Technical stop/original evidence incomplete or changed')
            manifest=util.read_json(root/'manifest.json'); condition=profiles.validate_run(root)
            machine.verify_conditions(root,fixed['conditions'],binding['condition'])
            from research.technical_pair_comparison import _settings_match
            _settings_match(condition,plan)
            if (manifest.get('run_instance_id')!=instance or manifest.get('stop_confirmed') is not True
                    or manifest.get('end_reason') in ('provider_failure','environment_failure','stop_unconfirmed','operator_stop')
                    or manifest['condition_sha256']!=binding['condition_sha256']
                    or manifest['prompt_sha256']!=binding['input_sha256']):
                raise ValueError('Technical manifest/condition/input not accepted')
            begin,finish=utc(manifest['started_at']),utc(manifest['ended_at'])
            if not start<=utc(binding['at'])<=begin<=finish<=end:
                raise ValueError('Dispatch/Run/publication timing inconsistent')
            windows[instance]=(begin,finish)
            runtime_state=util.read_json(root/'runtime.json')
            if runtime_state['run_instance_id']!=instance: raise ValueError('Resource owner changed')
            names[instance]=runtime_state['worker']
            usage=util.read_json(root/'usage/normalized.json')
            if (usage.get('usage_complete') is not True or usage.get('run_instance_id')!=instance
                    or usage.get('inventory_complete') is not True or type(usage.get('total_tokens')) is not int
                    or usage['total_tokens']<0): raise ValueError('Complete technical usage not established')
            starts,errors=live_usage.journal(root/'usage/raw/started.jsonl')
            events,event_errors=live_usage.journal(root/'usage/raw/events.jsonl')
            if errors or event_errors or not events or len(starts)!=len(events):
                raise ValueError('Actual request inventory missing/damaged')
            ids=[e['request_id'] for e in events]
            if len(set(ids))!=len(ids) or set(ids)!={e['request_id'] for e in starts}:
                raise ValueError('Actual request inventory conflict')
            observed=0; http[instance]=[]; request_measurements=[]
            for event in events:
                if (event.get('status')!='completed' or event.get('usage_complete') is not True
                        or event.get('session_id')!=instance or event.get('run_id')!=rid
                        or event.get('model_id')!=plan['settings']['model_id']
                        or event.get('response_model_id') not in (None,plan['settings']['model_id'])
                        or event.get('send_evidence')!='observed_send' or event.get('http_status')!=200):
                    raise ValueError('Actual provider transmission faulty or foreign')
                sent,ended=utc(event['transmitted_at']),utc(event['ended_at'])
                if not begin<=sent<=ended<=finish: raise ValueError('HTTP interval outside Run')
                received=utc(event['started_at']) if event.get('started_at') else None
                if received and not begin<=received<=sent: raise ValueError('Gateway request timing inconsistent')
                http[instance].append((sent,ended))
                request_measurements.append({'request_id':event['request_id'],
                    'transmitted_at':event['transmitted_at'],'ended_at':event['ended_at'],
                    'http_elapsed_seconds':(ended-sent).total_seconds(),
                    'gateway_before_send_seconds':(sent-received).total_seconds() if received else None,
                    'provider_queue_seconds':None})
                values=[event['usage'].get(k) for k in ('input_tokens','output_tokens')]
                if any(type(v) is not int or v<0 for v in values): raise ValueError('Usage incomplete/conflicting')
                observed+=sum(values)
            if observed!=usage['total_tokens']: raise ValueError('Provider/normalized total conflict')
            calls_total+=len(starts); tokens_total+=observed; run_seconds+=(finish-begin).total_seconds()
            run_measurements.append({'run_id':rid,'run_instance_id':instance,'condition':binding['condition'],
                'started_at':manifest['started_at'],'ended_at':manifest['ended_at'],
                'implementation_seconds':(finish-begin).total_seconds(),'usage_complete':True,
                'reported_tokens':observed,'requests':request_measurements})
        resources(block['resource_samples'],digest,number,windows,names)
        measured_blocks.append({'pair':number,'concurrency':block['concurrency'],
            'total_pair_elapsed_seconds':duration,'resource_samples':block['resource_samples'],
            'implementation_makespan_seconds':(max(end for begin,end in windows.values())-
                min(begin for begin,end in windows.values())).total_seconds(),
            'runs':run_measurements,
            'queue_limitation':'Gateway receive-to-send delay and HTTP elapsed are observed; provider internal queue is unobserved.'})
        if number==2:
            first,second=http.values()
            if not any(max(a,c)<min(b,d) for a,b in first for c,d in second):
                raise ValueError('Different-instance HTTP overlap was not observed')
    if seen!=set(assigned): raise ValueError('Not all four technical Runs observed')
    if (calls_total>=fixed['gateway_started_calls_stop'] or tokens_total>=fixed['reported_observed_tokens_stop']
            or run_seconds>=fixed['maximum_accumulated_run_seconds']):
        raise ValueError('Technical safety cap reached')
    if intervals[1][0]<intervals[0][1]: raise ValueError('Second pair began before first actual gate')
    if ('comparison_wall_clock_stop_seconds' in fixed and
            (intervals[1][1]-intervals[0][0]).total_seconds() >= fixed['comparison_wall_clock_stop_seconds']):
        raise ValueError('Total technical comparison wall-clock cap reached')
    if durations[1]>=durations[0]: raise ValueError('Observed paired total elapsed time did not improve')
    return {'accepted':True,'serial_total_seconds':durations[0],'paired_total_seconds':durations[1],
        'actual_dispatches':4,'gateway_calls':calls_total,'provider_reported_tokens':tokens_total,
        'distribution_equivalence_proven':False,'measurement_blocks':measured_blocks}


def ledger_reasons(ledger,plan,scopes):
    item=ledger.get('paired_execution_acceptance',{})
    if item.get('status')!='passed': return ['paired_execution_acceptance:'+item.get('status','not_run')]
    try: validate(read_reference(item['evidence']),plan,scopes)
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        return ['paired_execution_acceptance:original_comparison_not_accepted']
    return []
