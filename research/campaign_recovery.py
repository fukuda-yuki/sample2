"""Append-only, same-attempt campaign recovery and factual fault preservation.

No model entry point and no STOP removal. Acquisition originals stay immutable.
Only share_public performs external writes, after an exact public-byte review.
Fault publication is explicitly distinct from an acquisition success gate.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from outer.harness import evaluate, live_usage, preserve, run, util
from outer.harness.security import child_environment
from research import campaign_reassessment as assessment
from research import catalog_delivery as delivery, catalog_share as sharing
from research import live_pilot, pair_execution, repaired_runtime
from research.validation_scope import scoped_validation

KIND = 'repaired_campaign_factual_recovery_v1'
GATE_KIND = 'repaired_campaign_fault_publication_v1'
VALID = {'already_evaluable', 'normal_product_failure_partial_observation'}
CONTROLLER_KIND = 'repaired_campaign_recovery_controller_v1'
CONTROLLER_MINIMUM = frozenset(('research/campaign_recovery.py',
    'research/campaign_reassessment.py', 'research/saved_reassessment.py',
    'research/repaired_campaign.py', 'research/live_pilot.py',
    'research/pair_execution.py', 'research/catalog_delivery.py',
    'research/catalog_share.py', 'research/repaired_runtime.py',
    'outer/harness/preserve.py'))
INTENT_FIELDS = ('kind', 'campaign', 'wave', 'source_commit', 'recovery_controller',
    'launcher_closure', 'original_paths', 'original_inventory',
    'initial_logical_denominator', 'model_calls', 'acquisition_count_increment')


def complete_byte_inventory(root):
    """Inventory complete Windows paths without changing historical readers."""
    return {name: entry['sha256'] for name, entry in preserve.tree(root).items()}


def _pins_digest(pins):
    return util.sha256_bytes(json.dumps(pins, sort_keys=True, separators=(',', ':')).encode('utf-8'))


def _controller_names(repo, acquisition_plan):
    # Pin the existing acquisition applicability names using the RECOVERY
    # checkout's bytes, plus every local controller/helper this adapter may use.
    # Discover from the recorded checkout so a future reader need not have the
    # same controller inventory as the historical recovery implementation.
    return (set(acquisition_plan['source_pins']) | CONTROLLER_MINIMUM
        | set(assessment.saved.controller_inventory(repo))
        | {p.relative_to(repo).as_posix() for p in (repo/'research').glob('*.py')})


def _validate_controller(value, acquisition_plan):
    """Verify recorded code independently of this reader's import location."""
    if not isinstance(value, dict):
        raise ValueError('Missing recovery controller provenance')
    source_repo = value.get('source_repo')
    if not isinstance(source_repo, str) or not source_repo or not Path(source_repo).is_absolute():
        raise ValueError('Invalid recovery controller source path')
    repo = live_pilot.safe_path(source_repo)
    pins = value.get('source_pins')
    commit = value.get('source_commit', '')
    if (value.get('kind') != CONTROLLER_KIND
            or value.get('entrypoint') != 'research/campaign_recovery.py'
            or value.get('clean_committed_at_creation') is not True
            or not isinstance(commit, str) or not re.fullmatch('[a-f0-9]{40}', commit)
            or not isinstance(pins, dict) or not pins
            or any(not isinstance(h, str) or not re.fullmatch('[a-f0-9]{64}', h) for h in pins.values())
            or value.get('pins_sha256') != _pins_digest(pins)):
        raise ValueError('Invalid recovery controller provenance')
    if not _controller_names(repo, acquisition_plan) <= pins.keys():
        raise ValueError('Recovery controller applicability pins are incomplete')
    for name, digest in pins.items():
        repaired_runtime._relative(name)
        path = repo/name
        if path.is_symlink() or path.is_junction() or util.sha256_file(path) != digest:
            raise ValueError('Recovery controller source changed: ' + name)
    # A clean historical checkout and its exact HEAD are retained separately
    # from the acquisition checkout. Never silently substitute current imports.
    if (repaired_runtime._git(repo, 'rev-parse', 'HEAD') != commit
            or repaired_runtime._git(repo, 'status', '--porcelain')):
        raise ValueError('Recovery controller checkout changed')
    repaired_runtime._committed_files(repo, commit, pins)
    return value


def _capture_controller(acquisition_plan):
    """Require the actual executing checkout before creating any new output."""
    from research import repaired_campaign as campaign
    repo = Path(__file__).resolve().parents[1]
    if repaired_runtime._git(repo, 'status', '--porcelain'):
        raise ValueError('Clean committed recovery controller checkout required')
    commit = repaired_runtime._git(repo, 'rev-parse', 'HEAD')
    names = _controller_names(repo, acquisition_plan) | set(campaign.EXTRA_PINS)
    pins = {name: util.sha256_file(repo/name) for name in sorted(names)}
    # A mixed sys.path must not label old imported helpers as new controller code.
    for name, module in list(sys.modules.items()):
        if not (name.startswith('research.') or name.startswith('outer.harness.')):
            continue
        source = getattr(module, '__file__', None)
        if source and Path(source).suffix == '.py' and '.tests.' not in name:
            source = Path(source).resolve()
            if not source.is_relative_to(repo) or source.relative_to(repo).as_posix() not in pins:
                raise ValueError('Recovery controller imports a different source checkout')
    value = dict(kind=CONTROLLER_KIND, source_repo=str(repo), source_commit=commit,
        source_pins=pins, pins_sha256=_pins_digest(pins),
        entrypoint='research/campaign_recovery.py', clean_committed_at_creation=True)
    return _validate_controller(value, acquisition_plan)


def _read(ref):
    return util.read_json(live_pilot.checked(ref))


def _write(path, value):
    """Idempotence means exactly the same immutable value, never overwrite."""
    if Path(path).exists():
        if util.read_json(path) != value:
            raise ValueError('Retained recovery record differs')
    else:
        util.write_new_json(path, value)
    return live_pilot.reference(path)


def _safe_destination(path, protected):
    path = live_pilot.safe_path(path)
    for root in protected:
        root = live_pilot.safe_path(root)
        if path == root or path.is_relative_to(root) or root.is_relative_to(path):
            raise ValueError('Recovery destination overlaps source/protected evidence')
    return path


def _context(repo, campaign_plan_path, wave_path):
    from research import repaired_campaign as campaign
    repo = live_pilot.safe_path(repo)
    plan = campaign.validate(repo, campaign_plan_path)
    wave = campaign.wave_spec(repo, campaign_plan_path, wave_path)
    plan_ref, wave_ref = map(live_pilot.reference, (campaign_plan_path, wave_path))
    epoch = _read(wave['epoch_plan'])
    reservations = [e for e in campaign.ledger(plan)
                    if e.get('kind') == 'pair_attempt_reserved' and e.get('wave') == wave_ref]
    if len(reservations) != len(wave['pairs']) or {e['slot'] for e in reservations} != set(wave['pairs']):
        raise ValueError('Recovery needs exact durable wave reservations')
    for entry in reservations:
        pair = next(p for p in wave['assignments'] if p['pair'] == entry['slot'])
        if (entry['epoch_plan'] != wave['epoch_plan'] or entry['run_instances'] !=
                {c['condition']: c['run_instance_id'] for c in pair['cases']}):
            raise ValueError('Recovery reservation UUID differs')
    return dict(repo=repo, plan=plan, campaign=plan_ref, wave=wave, wave_ref=wave_ref,
                epoch=epoch, wave_path=live_pilot.safe_path(wave_path))


def _owned_closure(ctx):
    """Consume exact supervisor receipts; a generic process exit is insufficient."""
    path = ctx['wave_path'].parent/'_launcher/result.json'
    value = util.read_json(path)
    if (value.get('kind') != 'repaired_campaign_wave_launcher_v1_result'
            or value.get('plan') != ctx['campaign'] or value.get('wave') != ctx['wave_ref']
            or value.get('epoch_plan') != ctx['wave']['epoch_plan']
            or value.get('pairs') != ctx['wave']['pairs']
            or value.get('owned_closure_confirmed') is not True):
        raise ValueError('Exact supervisor-owned closure is required before recovery')
    if value.get('operational_complete') is True:
        proof = _read(value['verification']['evidence'])
        if (value['verification'].get('confirmed') is not True or proof.get('confirmed') is not True
                or proof.get('plan') != ctx['campaign'] or proof.get('wave') != ctx['wave_ref']):
            raise ValueError('Successful launcher closure lacks bound independent verification')
    else:
        rows = value.get('owned_runs', [])
        expected = {c['run_instance_id']: c for p in ctx['wave']['assignments'] for c in p['cases']}
        if (len(rows) != len(expected) or {r.get('run_instance_id') for r in rows} != set(expected)
                or value.get('child', {}).get('exit_confirmed') is not True
                or value.get('errors') != [] or value.get('stop', {}).get('errors') != []
                or value.get('observer_closure', {}).get('confirmed') is not True):
            raise ValueError('Fault closure does not establish every selected owned resource')
        for row in rows:
            case = expected[row['run_instance_id']]
            root = Path(ctx['epoch']['batch'])/('pair-'+str(case['pair']))/case['run_id']
            if (row.get('run_id') != case['run_id'] or live_pilot.safe_path(row['root']) != root
                    or row.get('unknown') is not False
                    or row.get('status') not in ('not_allocated', 'owned_allocated')
                    or row['status'] == 'owned_allocated' and row.get('closure_confirmed') is not True):
                raise ValueError('Unresolved or foreign fault closure row')
    return live_pilot.reference(path)


def usage_evidence(root, case):
    """Observed lower bounds remain separate from unknown total usage/send state."""
    root = Path(root)
    journals = {}
    errors = []
    refs = {}
    for name in ('started', 'events', 'transmission', 'failure'):
        path = root/'usage/raw'/(name+'.jsonl')
        rows, faults = live_usage.journal(path)
        journals[name] = rows
        errors.extend(faults)
        if path.exists(): refs[name] = live_pilot.reference(path)
        for row in rows:
            if (row.get('run_id') != case['run_id'] or name != 'failure'
                    and row.get('session_id') != case['run_instance_id']):
                errors.append('identity_mismatch:'+name)
    starts = [r.get('request_id') for r in journals['started']]
    ends = [r.get('request_id') for r in journals['events']]
    complete = (bool(starts) and len(set(starts)) == len(starts) and len(set(ends)) == len(ends)
                and set(starts) == set(ends) and not errors)
    totals = dict(input_tokens=0, output_tokens=0)
    provider = []
    for row in journals['events']:
        if row.get('run_id') != case['run_id'] or row.get('session_id') != case['run_instance_id']:
            continue
        for key in totals:
            number = row.get('usage', {}).get(key)
            if type(number) is int and number >= 0: totals[key] += number
            else: complete = False
        complete = complete and row.get('usage_complete') is True
        # A terminal provider/transport record is evidence. Run timeout, generated
        # program failure, cancelled requests and absent logs are not substitutes.
        if row.get('status') in ('provider_error', 'transport_error'):
            provider.append(dict(category='provider', status=row['status'],
                request_id=row.get('request_id'), http_status=row.get('http_status'),
                send_evidence=row.get('send_evidence'), evidence=refs.get('events')))
    if (root/'manifest.json').exists():
        try: send = live_usage.execution_evidence(root)
        except (OSError, ValueError, KeyError, TypeError): send = {'send_evidence':'unknown', 'issues':['invalid_manifest']}
    else:
        send = {'send_evidence':'unknown' if any(journals.values()) or (root/'runtime.json').exists()
                else 'known_no_send', 'issues':[]}
    # Completed terminal records explicitly reporting known_no_send resolve an
    # attempted request without pretending it was a transmission.
    if (not errors and starts and set(starts) == set(ends)
            and all(r.get('send_evidence') == 'known_no_send' for r in journals['events'])
            and not any((root/'usage/raw').glob('*.response.sse'))):
        send = {**send, 'send_evidence':'known_no_send', 'issues':[]}
    issues=list(send.get('issues', []))
    if (any(type(r) is not str or not r for r in starts+ends)
            or len(set(starts))!=len(starts) or len(set(ends))!=len(ends)
            or set(starts)!=set(ends)
            or any(r.get('request_id') not in starts for r in journals['transmission'])):
        issues.append('unreconciled_request_terminal_inventory')
    return dict(observed_requests=len(starts), observed_tokens=totals,
        usage_complete=bool(complete), total_tokens=sum(totals.values()) if complete else None,
        usage_unknown=not complete, send_evidence=send['send_evidence'],
        journal_errors=errors, transmission_issues=issues,
        source_journals=refs, technical_evidence=provider)


def _technical(root, case, usage):
    facts = list(usage['technical_evidence'])
    path = Path(root)/'implementation-receipt.json'
    if path.exists():
        receipt = util.read_json(path)
        if (receipt.get('run_id') == case['run_id'] and receipt.get('run_instance_id') == case['run_instance_id']
                and receipt.get('stop_confirmed') is True
                and receipt.get('collection_status') == 'collection_fault'):
            facts.append(dict(category='infrastructure_collection', evidence=live_pilot.reference(path)))
    record = evaluate.last_scoring(root) if (Path(root)/'evaluations').exists() else None
    if record and record.get('directory'):
        directory = live_pilot.safe_path(Path(root)/record['directory'])
        if not directory.is_relative_to(Path(root)/'evaluations'):
            raise ValueError('Scoring evidence escaped original')
        path = directory/'evaluation.json'
        if path.exists():
            output = util.read_json(path)
            if (output.get('reviewRunInstanceId') == case['run_instance_id']
                    and isinstance(output.get('evaluatorFaults'), list) and output['evaluatorFaults']):
                facts.append(dict(category='evaluator', evidence=live_pilot.reference(path)))
        path = directory/'browser-fault.json'
        if path.exists():
            # Byte evidence, plus the scoring record's explicit fault state; no
            # generated-program failure is promoted to an observer fault.
            if record.get('scoring_state') == 'evaluator_fault':
                facts.append(dict(category='browser_observer', evidence=live_pilot.reference(path)))
    return facts


def decide_pair(arms):
    """Pure same-attempt rule; no arm borrowing or quality-based replacement."""
    if set(arms) != {'explore', 'preload'}:
        raise ValueError('Exactly the two original attempt arms required')
    valid = [a['observation'].get('classification') in VALID or a.get('assessment_adopted') is True
             or a.get('assessment_valid_product_failure') is True
             for a in arms.values()]
    if all(valid): return 'accept_same_attempt'
    for arm in arms.values():
        usage = arm['usage']
        if (usage['send_evidence'] == 'unknown' or usage['journal_errors'] or usage['transmission_issues']
                or arm.get('opportunity') not in ('already_observed', 'exhausted', 'not_applicable')):
            return 'held'
    # At least one invalid arm needs positively classified technical evidence.
    # An already valid product failure is never itself a replacement reason.
    for arm, okay in zip(arms.values(), valid):
        if not okay and not arm.get('technical_evidence'):
            return 'held'
    return 'replacement_eligible'


def _acquisition_outcome(root, case):
    """Preserve acquisition termination separately from later evaluability."""
    path = Path(root)/'manifest.json'
    if not path.exists():
        return dict(manifest=None, end_reason=None, end_reason_observed=False)
    manifest = util.read_json(path)
    if (manifest.get('run_id') != case['run_id']
            or manifest.get('run_instance_id') != case['run_instance_id']):
        raise ValueError('Acquisition termination evidence has a foreign Run identity')
    return dict(manifest=live_pilot.reference(path), end_reason=manifest.get('end_reason'),
        end_reason_observed='end_reason' in manifest)


def _assess_arm(ctx, case, root, holder):
    outcome_path = holder/'outcome.json'
    if outcome_path.exists():
        value = util.read_json(outcome_path)
        if value['case'] != case: raise ValueError('Retained arm identity differs')
        if value.get('assessment'):
            assessment.revalidate(repo=ctx['repo'], result_ref=value['assessment'], main_plan_ref=ctx['wave']['epoch_plan'])
        return value
    observation = assessment.classify(repo=ctx['repo'], source=root, main_plan_ref=ctx['wave']['epoch_plan'])
    usage = usage_evidence(root, case)
    value = dict(case=case, observation=observation, usage=usage,
        acquisition_outcome=_acquisition_outcome(root, case),
        technical_evidence=_technical(root, case, usage), opportunity='not_applicable',
        assessment=None, assessment_adopted=False, assessment_valid_product_failure=False,
        valid_data=observation.get('classification') in VALID)
    if observation.get('classification') in VALID:
        value['opportunity'] = 'already_observed'
    elif observation.get('recoverable') is True:
        intent = holder/'assessment-intent.json'
        if intent.exists():
            retained = util.read_json(intent)
            ref = retained.get('prepared')
            results = list((holder/'assessments').glob('*/result.json'))
            if len(results) == 1:
                value['assessment'] = live_pilot.reference(results[0])
            elif ref is not None:
                value['opportunity'] = 'ambiguous'
            else:
                value['opportunity'] = 'ambiguous'
        else:
            _write(intent, dict(case=case, main_plan=ctx['wave']['epoch_plan'], model_calls=0))
            try:
                prepared = assessment.prepare(repo=ctx['repo'], source=root,
                    destination=holder/'assessments', main_plan_ref=ctx['wave']['epoch_plan'])
                _write(holder/'prepared.json', prepared)
                value['assessment'] = assessment.execute(repo=ctx['repo'], assessment_ref=prepared,
                    main_plan_ref=ctx['wave']['epoch_plan'], timeout=1800)
            except Exception as exc:
                # Keep the exact partial derivative and never repeat an ambiguous
                # evaluation as though nothing happened.
                value.update(opportunity='ambiguous', assessment_error_type=type(exc).__name__)
        if value.get('assessment'):
            result = assessment.revalidate(repo=ctx['repo'], result_ref=value['assessment'],
                main_plan_ref=ctx['wave']['epoch_plan'])
            value.update(opportunity='exhausted', assessment_adopted=result.get('adopted') is True,
                assessment_valid_product_failure=result.get('valid_product_failure') is True,
                valid_data=result.get('adopted') is True or result.get('valid_product_failure') is True,
                reassessed_quality=result.get('quality'))
            validation = result.get('validation') or {}
            if validation.get('observer_fault') is True:
                value['technical_evidence'].append(dict(category='reassessment_observer', evidence=value['assessment']))
    _write(outcome_path, value)
    return value


@scoped_validation
def recover_wave(repo, campaign_plan_path, wave_path, destination):
    """Preserve and assess once; publication/closure remains a separate operation."""
    ctx = _context(repo, campaign_plan_path, wave_path)
    destination = _safe_destination(destination, [ctx['repo'], ctx['plan']['batch'],
        *ctx['plan']['protected_roots']])
    target = destination/'decision.json'
    if target.exists():
        ref = live_pilot.reference(target); validate_recovery(repo, ref, campaign_plan_path, wave_path)
        return ref
    controller = _capture_controller(ctx['plan'])
    with assessment._existing_lock(Path(ctx['plan']['batch'])/'_control/dispatch.lock'):
        closure = _owned_closure(ctx)
        sources = {'wave':ctx['wave_path'].parent}
        sources.update({'pair-'+str(n):Path(ctx['epoch']['batch'])/('pair-'+str(n)) for n in ctx['wave']['pairs']})
        inventory = {name:complete_byte_inventory(path) for name,path in sources.items()}
        intent = dict(kind=KIND, campaign=ctx['campaign'], wave=ctx['wave_ref'],
            source_commit=ctx['plan']['source_commit'], recovery_controller=controller, launcher_closure=closure,
            original_paths={n:str(p) for n,p in sources.items()}, original_inventory=inventory,
            initial_logical_denominator=100, model_calls=0, acquisition_count_increment=0)
        _write(destination/'intent.json', intent)
        archive_path = destination/'original-archive.json'
        if archive_path.exists():
            archive = util.read_json(archive_path)
        else:
            archive = preserve.pack(destination/'private-archive', 'failed-wave-'+ctx['wave_ref']['sha256'][:24],
                sources, metadata=dict(kind=KIND, campaign_sha256=ctx['campaign']['sha256'],
                    wave_sha256=ctx['wave_ref']['sha256'], initial_logical_denominator=100,
                    recovery_controller_commit=controller['source_commit'],
                    recovery_controller_pins_sha256=controller['pins_sha256']))
            _write(archive_path, archive)
        preserved = preserve.verify(destination/'private-archive', archive['package_id'], archive['sha256'])
        expected = {name+'/'+rel:digest for name,rows in inventory.items() for rel,digest in rows.items()}
        if {n:v['sha256'] for n,v in preserved['files'].items()} != expected:
            raise ValueError('Whole failed attempt archive differs')
        decisions = {}
        for pair in ctx['wave']['assignments']:
            arms = {c['condition']:_assess_arm(ctx,c,sources['pair-'+str(pair['pair'])]/c['run_id'],
                destination/'arms'/c['run_instance_id']) for c in pair['cases']}
            decisions[str(pair['pair'])] = dict(disposition=decide_pair(arms),
                observations={k:a['observation'] for k,a in arms.items()},
                assessments={k:a['assessment'] for k,a in arms.items() if a.get('assessment')},
                arms=arms, run_instances={c['condition']:c['run_instance_id'] for c in pair['cases']},
                quality={k:a.get('reassessed_quality',a['observation'].get('quality')) for k,a in arms.items()},
                numeric_complete=all((a.get('assessment_adopted') or a['observation'].get('classification')=='already_evaluable') for a in arms.values()))
            decisions[str(pair['pair'])]['quality_complete']=decisions[str(pair['pair'])]['numeric_complete']
        if any(complete_byte_inventory(path) != inventory[name] for name,path in sources.items()):
            raise ValueError('Original evidence changed during separate recovery')
        _validate_controller(controller, ctx['plan'])
        from research import repaired_campaign as campaign
        prior = campaign.ledger(ctx['plan'])
        attempts = max(sum(e.get('kind')=='pair_attempt_reserved' and e.get('slot')==n for e in prior)
                       for n in ctx['wave']['pairs'])
        delays = ctx['plan']['bounds']['retry_backoff_seconds']
        delay = delays[min(max(attempts-1,0),len(delays)-1)]
        now = datetime.now(timezone.utc)
        value = dict(**intent, original_archive=archive, decisions=decisions,
            backoff_seconds=delay, decided_at=now.isoformat(), retry_not_before=(now+timedelta(seconds=delay)).isoformat(),
            closed=False, publication_pending=True, resend_authorized=False,
            all_attempts_retained=True, cross_attempt_arm_composition=False)
        return _write(target,value)


@scoped_validation
def validate_recovery(repo, recovery_ref, campaign_plan_path, wave_path):
    ctx = _context(repo,campaign_plan_path,wave_path)
    path = live_pilot.checked(recovery_ref); value = util.read_json(path)
    from research import proof_session
    # Reservation/ledger/current campaign checks above remain fresh. Only the
    # retained evidence body may be shared across operations.
    # Before the administrative wrapper exists, publication/closure can still
    # append evidence. Do not pin that unfinished tree across operations.
    closure = path.parent/'closure.json'
    wrappers = [ctx['wave_path'].parent/name for name in ('closure.json','recovery-closure.json')]
    sealed = closure.exists() and any(wrapper.exists() and util.read_json(wrapper) ==
        dict(wave=ctx['wave_ref'],closed=True,recovery=live_pilot.reference(closure)) for wrapper in wrappers)
    if not sealed:
        return _validate_recovery_evidence(ctx,path,value)
    arguments = dict(context={k:str(v) if isinstance(v,Path) else v for k,v in ctx.items()},
        path=str(path),value=value)
    return proof_session.use('recovery-evidence',arguments,
        lambda: _validate_recovery_evidence(ctx,path,value))


def _validate_recovery_evidence(ctx,path,value):
    repo = ctx['repo']
    if (path.name!='decision.json' or value.get('kind')!=KIND or value.get('campaign')!=ctx['campaign']
            or value.get('wave')!=ctx['wave_ref'] or value.get('initial_logical_denominator')!=100
            or value.get('model_calls')!=0 or value.get('acquisition_count_increment')!=0
            or value.get('all_attempts_retained') is not True or value.get('resend_authorized') is not False
            or value.get('launcher_closure')!=_owned_closure(ctx)
            or value.get('source_commit')!=ctx['plan']['source_commit']):
        raise ValueError('Foreign recovery decision')
    intent = util.read_json(path.parent/'intent.json')
    if set(intent) != set(INTENT_FIELDS) or intent != {k:value.get(k) for k in INTENT_FIELDS}:
        raise ValueError('Recovery decision differs from its immutable intent')
    _validate_controller(value.get('recovery_controller'), ctx['plan'])
    for name, original in value['original_paths'].items():
        current=complete_byte_inventory(live_pilot.safe_path(original))
        expected=value['original_inventory'][name]
        extra=set(current)-set(expected)
        # The campaign appends one administrative wrapper only after this
        # closure exists. Existing normal closure bytes are never overwritten.
        for addition in extra:
            target=Path(original)/addition
            closure=path.parent/'closure.json'
            if (name!='wave' or addition not in ('closure.json','recovery-closure.json')
                    or not closure.exists() or util.read_json(target)!=dict(wave=value['wave'],closed=True,
                        recovery=live_pilot.reference(closure))):
                raise ValueError('Unexpected additions to original fault evidence')
        if {n:h for n,h in current.items() if n in expected} != expected:
            raise ValueError('Original fault evidence changed')
    archive = value['original_archive']
    preserved = preserve.verify(path.parent/'private-archive',archive['package_id'],archive['sha256'])
    expected = {name+'/'+rel:digest for name,rows in value['original_inventory'].items() for rel,digest in rows.items()}
    if {n:v['sha256'] for n,v in preserved['files'].items()} != expected:
        raise ValueError('Private original archive changed')
    if set(value['decisions']) != {str(n) for n in ctx['wave']['pairs']}:
        raise ValueError('Recovery omitted a fixed logical pair')
    for pair in ctx['wave']['assignments']:
        decision = value['decisions'][str(pair['pair'])]
        if decision['run_instances'] != {c['condition']:c['run_instance_id'] for c in pair['cases']}:
            raise ValueError('Recovery combined different paired attempts')
        for case in pair['cases']:
            arm = decision['arms'][case['condition']]
            if arm['case'] != case: raise ValueError('Recovery arm identity differs')
            root=Path(ctx['epoch']['batch'])/('pair-'+str(pair['pair']))/case['run_id']
            if arm.get('acquisition_outcome') != _acquisition_outcome(root,case):
                raise ValueError('Recovery changed the preserved acquisition end reason')
            if arm['usage']!=usage_evidence(root,case): raise ValueError('Recovery usage differs from saved originals')
            technical=_technical(root,case,arm['usage'])
            if arm['observation'].get('classification') in VALID:
                _,binding,_=assessment._source_binding(repo,root,ctx['wave']['epoch_plan'],observe_resources=False)
                observed=assessment._observation(root,util.read_json(root/'condition.json'),binding['run_instance_id'])
                if any(arm['observation'].get(k)!=v for k,v in observed.items()):
                    raise ValueError('Claimed original observation is not reproducible')
            if arm.get('assessment'):
                a = assessment.revalidate(repo=repo,result_ref=arm['assessment'],main_plan_ref=ctx['wave']['epoch_plan'])
                if (a['source_run_instance_id']!=case['run_instance_id'] or a.get('adopted')!=arm['assessment_adopted']
                        or (a.get('valid_product_failure') is True)!=arm.get('assessment_valid_product_failure',False)
                        or a.get('quality')!=arm.get('reassessed_quality')):
                    raise ValueError('Separate assessment adoption differs')
                if (a.get('validation') or {}).get('observer_fault') is True:
                    technical.append(dict(category='reassessment_observer',evidence=arm['assessment']))
            elif (arm.get('assessment_adopted') is True or arm.get('assessment_valid_product_failure') is True
                    or arm.get('opportunity')=='exhausted'):
                raise ValueError('Missing saved-assessment receipt')
            if technical!=arm['technical_evidence']: raise ValueError('Technical replacement evidence differs')
        if decision['disposition'] != decide_pair(decision['arms']):
            raise ValueError('Unsupported replacement or adoption decision')
        arms=decision['arms']
        complete=all(a.get('assessment_adopted') or a['observation'].get('classification')=='already_evaluable' for a in arms.values())
        if (decision.get('observations')!={k:a['observation'] for k,a in arms.items()}
                or decision.get('assessments')!={k:a['assessment'] for k,a in arms.items() if a.get('assessment')}
                or decision.get('quality')!={k:a.get('reassessed_quality',a['observation'].get('quality')) for k,a in arms.items()}
                or decision.get('quality_complete')!=complete or decision.get('numeric_complete')!=complete):
            raise ValueError('Recovery decision projection differs from original arms')
    return value


# This standalone reader needs only the delivered JSON; it never loads an app,
# evaluator, native log or database, and verifies every public member first.
READER = '''import hashlib,json,sys
from pathlib import Path
sys.addaudithook(lambda e,a: (_ for _ in ()).throw(RuntimeError("Network forbidden")) if e.startswith("socket.") else None)
root=Path(__file__).resolve().parent
m=json.loads((root/"MANIFEST.json").read_text(encoding="utf-8"))
for row in m["files"]:
 p=root/row["path"]
 assert p.resolve().is_relative_to(root) and not p.is_symlink()
 assert p.stat().st_size==row["bytes"] and hashlib.sha256(p.read_bytes()).hexdigest()==row["sha256"]
d=json.loads((root/"fault-data.json").read_text(encoding="utf-8"))
print(json.dumps(d,sort_keys=True,separators=(",",":")))
'''


def _public_data(value, slot):
    decision = value['decisions'][str(slot)]
    arms = {}
    for condition, arm in decision['arms'].items():
        usage = arm['usage']
        outcome = arm['acquisition_outcome']
        arms[condition] = dict(run_id=arm['case']['run_id'],run_instance_id=arm['case']['run_instance_id'],
            acquisition_end_reason=outcome['end_reason'],
            acquisition_end_reason_observed=outcome['end_reason_observed'],
            acquisition_manifest_sha256=outcome['manifest']['sha256'] if outcome['manifest'] else None,
            classification=arm['observation']['classification'],valid_data=arm['valid_data'],
            assessment_adopted=arm['assessment_adopted'],quality=decision['quality'][condition],
            assessment_valid_product_failure=arm.get('assessment_valid_product_failure',False),
            opportunity=arm['opportunity'],observed_requests=usage['observed_requests'],
            observed_tokens=usage['observed_tokens'],usage_complete=usage['usage_complete'],
            total_tokens=usage['total_tokens'],usage_unknown=usage['usage_unknown'],
            send_evidence=usage['send_evidence'],technical_categories=sorted({f['category'] for f in arm['technical_evidence']}),
            assessment_receipt_sha256=arm['assessment']['sha256'] if arm.get('assessment') else None)
    return dict(kind=KIND,campaign_sha256=value['campaign']['sha256'],wave_sha256=value['wave']['sha256'],
        source_commit=value['source_commit'],initial_logical_denominator=100,slot=slot,
        acquisition_source_commit=value['source_commit'],
        recovery_controller_commit=value['recovery_controller']['source_commit'],
        recovery_controller_pins_sha256=value['recovery_controller']['pins_sha256'],
        disposition=decision['disposition'],numeric_complete=decision['numeric_complete'],arms=arms,
        original_pair_inventory=value['original_inventory']['pair-'+str(slot)],
        private_archive_sha256=value['original_archive']['sha256'],model_calls_for_recovery=0,
        acquisition_count_increment=0,usage_counted_once_in_original_attempt=True,
        limitations=['Raw logs, private evaluator assets, databases and full originals are retained privately.',
                    'This factual fault package is not an acquisition-success or product-quality gate.',
                    'Missing total usage is unknown, not zero; observed tokens are lower bounds.'])


@scoped_validation
def stage_public(repo, recovery_ref, slot, destination):
    value = _read(recovery_ref)
    validate_recovery(repo,recovery_ref,value['campaign']['path'],value['wave']['path'])
    if str(slot) not in value['decisions']: raise ValueError('Unassigned recovery slot')
    destination = _safe_destination(destination,[repo,Path(recovery_ref['path']).parent,
        *map(Path,value['original_paths'].values())])
    path = destination/'stage.json'
    if path.exists():
        staged=util.read_json(path)
        if staged.get('recovery')!=recovery_ref or staged.get('slot')!=slot: raise ValueError('Foreign public staging')
        sharing.verify_public(destination/'public',exact=True)
        return live_pilot.reference(path)
    public=destination/'public'; public.mkdir(parents=True,exist_ok=False)
    _write(public/'fault-data.json',_public_data(value,slot))
    (public/'reproduce.py').write_text(READER,encoding='utf-8',newline='\n')
    (public/'README.md').write_text('Factual campaign recovery evidence\n\nRun `python -I -B reproduce.py` to verify public bytes and reproduce the data.\n'
        'Both original arms remain paired. Product failures remain valid data, including null quality. '
        'This publication does not claim full private evaluator reproducibility.\n',encoding='utf-8')
    files=[dict(path=name,**row) for name,row in sharing.inventory(public).items()]
    _write(public/'MANIFEST.json',dict(kind=GATE_KIND,plan_sha256=value['campaign']['sha256'],pair=slot,
        selected_runs=[a['case']['run_id'] for a in value['decisions'][str(slot)]['arms'].values()],
        files=files,excluded=['private original archive','raw provider and agent logs','private evaluator assets','databases']))
    sharing.verify_public(public,exact=True)
    sharing.scan(public,destination/'scan.json')
    return _write(path,dict(kind=GATE_KIND,recovery=recovery_ref,slot=slot,
        public_inventory=sharing.inventory(public),publication_approved=False))


def _extract(root, output):
    result=subprocess.run([sys.executable,'-I','-B',str(Path(root)/'reproduce.py')],cwd=root,
        env=child_environment(),capture_output=True,text=True,timeout=60)
    if result.returncode: raise ValueError('Offline factual extraction failed')
    value=json.loads(result.stdout)
    _write(output,value)
    return live_pilot.reference(output)


def _roundtrip(asset,urls,workspace):
    workspace=live_pilot.safe_path(workspace); workspace.mkdir(parents=True,exist_ok=False)
    download=workspace/'download'; download.mkdir()
    for part in asset['parts']:
        if len(sharing.safe_member(part['name']).parts)!=1: raise ValueError('Unsafe asset part')
        target=download/part['name']; delivery.download(urls[part['name']],target)
        if target.stat().st_size!=part['bytes'] or util.sha256_file(target)!=part['sha256']:
            raise ValueError('Anonymous downloaded part differs')
    archive=download/asset['asset']
    if len(asset['parts'])!=1 or asset['parts'][0]['name']!=asset['asset']:
        with archive.open('xb') as out:
            for part in asset['parts']:
                with (download/part['name']).open('rb') as stream: shutil.copyfileobj(stream,out)
    local=workspace/'verified-asset-manifest.json'; _write(local,asset)
    metadata={}
    for name,digest in [('pair.manifest.json',util.sha256_file(local)),('public-review.json',asset['review_sha256']),('scan.json',asset['scan_sha256'])]:
        target=download/name; delivery.download(urls[name],target)
        if util.sha256_file(target)!=digest: raise ValueError('Anonymous metadata differs')
        metadata[name]=digest
    restored=workspace/'restored'; verified=sharing.restore(archive,local,restored)
    extraction=_extract(restored,workspace/'extraction.json')
    return dict(**verified,metadata_hashes=metadata,download_urls=urls,workspace=str(workspace),
        extraction_sha256=extraction['sha256'],extraction_sockets_blocked=True,
        model_called=False,evaluator_called=False,package_sha256=asset['sha256'])


@scoped_validation
def share_public(repo,recovery_ref,slot,workspace,review):
    """Explicit actual publication after review; ambiguous transfer is reconciled."""
    value=_read(recovery_ref); validate_recovery(repo,recovery_ref,value['campaign']['path'],value['wave']['path'])
    workspace=live_pilot.safe_path(workspace); staged=util.read_json(workspace/'stage.json')
    if staged.get('recovery')!=recovery_ref or staged.get('slot')!=slot: raise ValueError('Foreign public staging')
    if (workspace/'fault-gate.json').exists():
        ref=live_pilot.reference(workspace/'fault-gate.json'); _verify_publication(ref,recovery_ref,slot)
        return ref
    if (workspace/'cleanup.json').exists():
        # Recover a crash after scratch cleanup but before gate publication.
        candidates=sorted(workspace.glob('roundtrip-*/roundtrip.json'))
        if not candidates: raise ValueError('Cleanup lacks retained roundtrip evidence')
        pub=util.read_json(workspace/'publication.json')
        gate=dict(kind=GATE_KIND,recovery=recovery_ref,slot=slot,campaign=value['campaign'],wave=value['wave'],
            source_commit=value['source_commit'],quality_acceptance=False,acquisition_success=False,
            public_review=live_pilot.reference(workspace/'review.json'),
            publication=live_pilot.reference(workspace/'publication.json'),roundtrip=live_pilot.reference(candidates[-1]),
            cleanup=live_pilot.reference(workspace/'cleanup.json'),before_extraction=live_pilot.reference(workspace/'before-extraction.json'),
            package_sha256=pub['asset_manifest']['sha256'])
        ref=_write(workspace/'fault-gate.json',gate);_verify_publication(ref,recovery_ref,slot)
        return ref
    public=workspace/'public'; sharing.verify_public(public,exact=True)
    if sharing.inventory(public)!=staged['public_inventory']: raise ValueError('Public projection changed')
    decision=util.read_json(review)
    if decision.get('publication_approved') is not True or decision.get('reviewed_inventory')!=staged['public_inventory']:
        raise ValueError('Exact public-byte review required')
    retained_review=workspace/'review.json'
    if retained_review.exists():
        if util.sha256_file(retained_review)!=util.sha256_file(review): raise ValueError('Exact review bytes changed')
    else:
        with retained_review.open('xb') as stream:stream.write(Path(review).read_bytes())
    review_ref=live_pilot.reference(retained_review)
    before=_extract(public,workspace/'before-extraction.json')
    asset=delivery.package(public,workspace/'package',review)
    prefix='technical-continuity-'+value['wave']['sha256'][:12]+'-pair-'; tag=prefix+f'{slot:03d}'
    urls=delivery.publish(workspace/'package',tag,value['source_commit'],tag_prefix=prefix)
    remote=delivery.release(tag)
    tag_object=json.loads(delivery.gh('api','repos/'+delivery.REPOSITORY+'/git/ref/tags/'+tag))['object']
    for _ in range(5):
        if tag_object.get('type')=='commit': break
        if tag_object.get('type')!='tag': raise ValueError('Unexpected remote tag object')
        tag_object=json.loads(delivery.gh('api','repos/'+delivery.REPOSITORY+'/git/tags/'+tag_object['sha']))['object']
    if not remote or tag_object.get('type')!='commit' or tag_object.get('sha')!=value['source_commit']:
        raise ValueError('Actual remote commit differs')
    remote_ref=_write(workspace/'remote.json',dict(tag_name=tag,tag_commit=tag_object['sha'],
        release_id=remote['id'],html_url=remote['html_url'],assets=[{k:r[k] for k in
            ('id','name','size','digest','browser_download_url')} for r in remote['assets']]))
    publication=_write(workspace/'publication.json',dict(kind=GATE_KIND,transport_mode='github-release-anonymous-download-v1',
        asset_manifest=asset,actual_remote_readback=remote_ref,urls=urls,remote_assets_verified=True))
    # A failed roundtrip is retained under its unique directory; a new local
    # download is safe because it neither submits models nor repeats an upload.
    number=1+len(list(workspace.glob('roundtrip-*')))
    restored=_roundtrip(asset,urls,workspace/f'roundtrip-{number:03d}')
    if restored['extraction_sha256']!=before['sha256']: raise ValueError('Relocated extraction differs')
    roundtrip=_write(Path(restored['workspace'])/'roundtrip.json',restored)
    cleanup=_write(workspace/'cleanup.json',delivery.cleanup(workspace,workspace.parent,restored))
    gate=dict(kind=GATE_KIND,recovery=recovery_ref,slot=slot,campaign=value['campaign'],wave=value['wave'],
        source_commit=value['source_commit'],quality_acceptance=False,acquisition_success=False,
        public_review=review_ref,publication=publication,roundtrip=roundtrip,cleanup=cleanup,
        before_extraction=before,package_sha256=asset['sha256'])
    return _write(workspace/'fault-gate.json',gate)


def _verify_publication(ref,recovery_ref,slot):
    path=live_pilot.checked(ref); gate=util.read_json(path); value=_read(recovery_ref)
    if (path.name!='fault-gate.json' or gate.get('kind')!=GATE_KIND or gate.get('recovery')!=recovery_ref
            or gate.get('slot')!=slot or gate.get('campaign')!=value['campaign'] or gate.get('wave')!=value['wave']
            or gate.get('quality_acceptance') is not False or gate.get('acquisition_success') is not False
            or gate.get('source_commit')!=value['source_commit']): raise ValueError('Foreign factual publication gate')
    pub,restored,cleanup,review=map(_read,(gate['publication'],gate['roundtrip'],gate['cleanup'],gate['public_review']))
    remote=_read(pub['actual_remote_readback']); asset=pub['asset_manifest']
    tag='technical-continuity-'+value['wave']['sha256'][:12]+'-pair-'+f'{slot:03d}'
    if (pub.get('transport_mode')!='github-release-anonymous-download-v1' or pub.get('remote_assets_verified') is not True
            or remote.get('tag_name')!=tag or remote.get('tag_commit')!=value['source_commit']
            or type(remote.get('release_id')) is not int or remote['release_id']<=0
            or remote.get('html_url')!='https://github.com/'+delivery.REPOSITORY+'/releases/tag/'+tag
            or review.get('publication_approved') is not True or review.get('reviewed_inventory')!=asset['file_inventory']
            or gate['public_review']['sha256']!=asset['review_sha256']
            or asset.get('plan_sha256')!=value['campaign']['sha256'] or asset.get('pair')!=slot
            or asset.get('selected_runs')!=[a['case']['run_id'] for a in value['decisions'][str(slot)]['arms'].values()]
            or asset['sha256']!=gate['package_sha256'] or restored.get('package_sha256')!=asset['sha256']
            or restored.get('hashes_match') is not True or restored.get('extraction_sockets_blocked') is not True
            or restored.get('model_called') is not False or restored.get('evaluator_called') is not False
            or restored.get('extraction_sha256')!=gate['before_extraction']['sha256']
            or _read(gate['before_extraction'])!=_public_data(value,slot)
            or cleanup.get('cleanup_completed') is not True or cleanup.get('original_runs_deleted') is not False):
        raise ValueError('Factual publication/restore/cleanup proof invalid')
    from research import paired_acceptance
    paired_acceptance.actual_remote(dict(publication_receipt=gate['publication']['path'],
        roundtrip_receipt=gate['roundtrip']['path'],evidence_files={pub['actual_remote_readback']['path']:pub['actual_remote_readback']['sha256']}))
    transfer=live_pilot.safe_path(restored['workspace'])
    if transfer.parent!=path.parent: raise ValueError('Foreign restored workspace')
    if (util.sha256_file(transfer/'extraction.json')!=restored['extraction_sha256']
            or util.read_json(transfer/'verified-asset-manifest.json')!=asset):
        raise ValueError('Retained independent restoration evidence changed')
    targets=[path.parent/'public',path.parent/'package',transfer/'download',transfer/'restored']
    if cleanup.get('targets')!=[str(t) for t in targets] or any(t.exists() for t in targets):
        raise ValueError('Owned public scratch cleanup incomplete')
    return gate


@scoped_validation
def close_recovery(repo,campaign_plan_path,wave_path,recovery_ref,publication_refs):
    value=validate_recovery(repo,recovery_ref,campaign_plan_path,wave_path)
    if set(publication_refs)!=set(value['decisions']): raise ValueError('Every wave pair needs factual publication')
    for slot,ref in publication_refs.items(): _verify_publication(ref,recovery_ref,int(slot))
    closure=dict(kind=KIND,closed=True,campaign=value['campaign'],wave=value['wave'],recovery=recovery_ref,
        decisions=value['decisions'],backoff_seconds=value['backoff_seconds'],retry_not_before=value['retry_not_before'],
        publication_gates=publication_refs,initial_logical_denominator=100,
        acquisition_success=False,all_attempts_retained=True,model_calls=0)
    ref=_write(Path(recovery_ref['path']).parent/'closure.json',closure)
    validate_closure(repo,campaign_plan_path,wave_path,ref)
    return ref


@scoped_validation
def validate_closure(repo,campaign_plan_path,wave_path,closure_ref):
    """Pure bounded local validation for campaign reservation/STOP clearances."""
    path=live_pilot.checked(closure_ref); value=util.read_json(path)
    recovery=validate_recovery(repo,value['recovery'],campaign_plan_path,wave_path)
    if (path!=Path(value['recovery']['path']).parent/'closure.json' or value.get('kind')!=KIND
            or value.get('closed') is not True or value.get('campaign')!=recovery['campaign']
            or value.get('wave')!=recovery['wave'] or value.get('decisions')!=recovery['decisions']
            or value.get('backoff_seconds')!=recovery['backoff_seconds']
            or value.get('retry_not_before')!=recovery['retry_not_before']
            or value.get('initial_logical_denominator')!=100 or value.get('acquisition_success') is not False
            or value.get('all_attempts_retained') is not True or value.get('model_calls')!=0
            or set(value['publication_gates'])!=set(recovery['decisions'])):
        raise ValueError('Recovery closure changed')
    for slot,ref in value['publication_gates'].items(): _verify_publication(ref,value['recovery'],int(slot))
    return value
