"""Reconcile gateway originals, input interventions and native execution evidence."""
import json
import re
from datetime import datetime
from pathlib import Path

from . import util, run, gateway


def execution_evidence(root):
    """Reconcile activity without treating controller intent as transmission."""
    root = Path(root)
    manifest = util.read_json(root / 'manifest.json')
    raw = root / 'usage/raw'
    identity = (manifest['run_id'], manifest.get('run_instance_id', manifest['run_id']))
    starts, start_errors = journal(raw / 'started.jsonl')
    ends, end_errors = journal(raw / 'events.jsonl')
    sends, send_errors = journal(raw / 'transmission.jsonl')
    records = [e for e in starts + ends + sends
               if (e.get('run_id'), e.get('session_id')) == identity]
    wrong = len(records) != len(starts + ends + sends)
    responses = [p.name for p in raw.glob('*.response.sse') if p.stat().st_size]
    attributed_responses = set(responses) & {e.get('response_file') for e in records}
    observed = bool(attributed_responses or any(e.get('send_evidence') == 'observed_send'
                    or e.get('http_status') is not None for e in records))
    runtime_path = root / 'runtime.json'
    state = util.read_json(runtime_path) if runtime_path.exists() else {}
    errors = start_errors + end_errors + send_errors + (['identity_mismatch'] if wrong else [])
    # A disappeared journal from an already started worker cannot prove no send.
    uncertain = bool(errors or responses or records or state.get('worker_started_at'))
    send = ('observed_send' if observed else 'unknown' if uncertain else 'known_no_send')
    return {'evidence_version': 3, 'send_evidence': send,
            'model_called': True if observed else None if uncertain else False,
            'provider_acknowledged': any(e.get('http_status') is not None for e in records),
            'saved_response_count': len(responses), 'started_count': len(starts),
            'attributed_saved_response_count': len(attributed_responses),
            'terminal_count': len(ends), 'issues': errors,
            'raw_sha256': {p.name: util.sha256_file(p) for p in sorted(raw.glob('*')) if p.is_file()}}


def update_manifest_evidence(root):
    evidence = execution_evidence(root)
    manifest = util.read_json(Path(root) / 'manifest.json')
    manifest.update(model_called=evidence['model_called'], execution_evidence=evidence)
    run.save_manifest(Path(root).parent, Path(root).name, manifest)
    return evidence


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


def journal(path):
    """Keep valid lines from an interrupted spool; a damaged line invalidates coverage."""
    path = Path(path)
    records, errors = [], []
    if not path.exists():
        return records, errors
    for number, raw in enumerate(path.read_bytes().splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError('Expected object')
            records.append(value)
        except (ValueError, UnicodeError):
            errors.append(path.name + ':invalid_line:' + str(number))
    return records, errors


def input_locations(messages, original):
    """Map an original to raw input or OpenCode's documented Read rendering.

    Only consecutive numbered lines are decoded. No whitespace, source text or
    missing lines are guessed. The final newline is not represented by Read.
    """
    found = []
    target = original.splitlines()
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or message.get('role') != 'user':
            continue
        for content_index, value in enumerate(strings(message.get('content'))):
            if original in value:
                found.append({'message_index': index, 'string_index': content_index,
                              'rendering': 'verbatim'})
                continue
            match = re.search(r'<content>\r?\n(.*?)\r?\n\(End of file - total (\d+) lines\)\r?\n</content>',
                              value, re.DOTALL)
            if not match:
                continue
            numbered = re.findall(r'(?m)^(\d+): (.*)\r?$', match[1])
            numbers = [int(n) for n, _ in numbered]
            decoded = [line.rstrip('\r') for _, line in numbered]
            if (numbers != list(range(1, len(numbered) + 1))
                    or len(numbered) != int(match[2])):
                continue
            for offset in range(len(decoded) - len(target) + 1):
                if decoded[offset:offset + len(target)] == target:
                    found.append({'message_index': index, 'string_index': content_index,
                        'rendering': 'opencode-read-numbered-lines', 'first_line': offset + 1,
                        'last_line': offset + len(target), 'terminal_newline': 'not represented by Read'})
    return found


def reconcile(started, ended, run_id, session_id=None):
    session_id = session_id or run_id
    issues, starts, ends = [], {}, {}
    for events, dest in ((started, starts), (ended, ends)):
        for e in events:
            if e.get('run_id') != run_id or e.get('session_id') != session_id:
                issues.append('identity_mismatch')
                continue
            rid = e.get('request_id')
            if not rid or rid in dest:
                issues.append('duplicate_or_missing_request_id')
            else:
                dest[rid] = e
    if set(ends) != set(starts):
        issues.append('incomplete_call_inventory')
    events = []
    for rid, begin in starts.items():
        end = ends.get(rid)
        if end and any(begin.get(k) != end.get(k) for k in
                       ('run_id', 'session_id', 'event_id', 'model_id', 'request_sha256')):
            issues.append('event_identity_changed')
            end = None
        e = end or begin
        if e.get('status') != 'completed' or e.get('policy_error'):
            issues.append('request_not_completed')
        events.append(e)
    if not starts:
        issues.append('no_calls_observed')
    return events, sorted(set(issues))


def staged_evidence(root, manifest, events, native_sessions):
    """Bind controller intent, native ACK and independently retained gateway bytes.

    An observed request is not a send, and a native ACK is not provider receipt.
    Ordinary failure/unreached outcomes are retained without discarding usage.
    """
    from . import staged_input
    root = Path(root); raw = root/'usage/raw'; errors = []
    reference = manifest.get('staged_input')
    if not reference:
        return None, ['undeclared_staged_input'] if (raw/'staged-input.jsonl').exists() else []
    try:
        contract_path = Path(reference['contract_path'])
        if util.sha256_file(contract_path) != reference['contract_sha256']:
            raise ValueError('Staged contract changed')
        controller = staged_input.Controller(contract_path.parent)
        contract = controller.contract; state = controller.status(); ledger = controller.events()
        if (contract['run_id'], contract['run_instance_id']) != (manifest['run_id'], manifest['run_instance_id']):
            raise ValueError('Staged Run identity mismatch')
        if util.sha256_file(root/'inputs/prompt.txt') != contract['initial_sha256']:
            raise ValueError('Staged initial input mismatch')
        expected = (controller.root/'additional.txt').read_bytes().decode('utf-8')
        records, journal_errors = journal(raw/'staged-input.jsonl'); errors += journal_errors
        arms = [r for r in records if r.get('kind') == 'armed']
        plans = [r for r in records if r.get('kind') == 'planned']
        observed = [r for r in records if r.get('kind') == 'request_checked']
        identity = {'run_id': contract['run_id'], 'run_instance_id': contract['run_instance_id'],
                    'contract_sha256': reference['contract_sha256'], 'delivery_id': contract['delivery_id']}
        if len(plans) != 1 or len(arms) > 1 or any(any(r.get(k) != v for k,v in identity.items()) for r in records):
            errors.append('stage_gateway_binding_mismatch')
        proof_by_request = {r.get('request_id'): r for r in observed}
        if len(proof_by_request) != len(observed): errors.append('stage_duplicate_request_proof')
        intents = [e for e in ledger if e['kind'] == 'send_intent']
        boundaries = [e for e in ledger if e['kind'] == 'boundary_observed']
        sessions = [e['native_session_id'] for e in ledger if e['kind'] == 'native_session']
        if len(sessions) != 1 or native_sessions != sessions:
            errors.append('stage_native_session_mismatch')
        if arms and (len(intents) != 1 or len(boundaries) != 1 or arms[0]['native_session_id'] not in sessions
                     or arms[0]['additional_sha256'] != contract['additional_sha256']):
            errors.append('stage_unbound_arm')
        if arms and boundaries and arms[0]['barrier_id'] != boundaries[0]['fence']['barrier_id']:
            errors.append('stage_boundary_binding_mismatch')
        barriers=[]
        if contract['boundary_contract'].get('transport') == 'opencode-server-response-barrier-v1':
            barriers, faults = journal(raw/'response-barriers.jsonl'); errors += faults
            held = [r for r in barriers if r.get('kind') == 'held']
            released = [r for r in barriers if r.get('kind') == 'released']
            if (len({r['barrier_id'] for r in held}) != len(held)
                    or len({r['barrier_id'] for r in released}) != len(released)
                    or any(r.get(k) != contract[k] for r in barriers for k in ('run_id','run_instance_id'))):
                errors.append('stage_response_barrier_identity')
            for release in released:
                originals = [h for h in held if h['barrier_id']==release['barrier_id']]
                if len(originals)!=1 or any(release.get(k)!=v for k,v in originals[0].items() if k not in ('kind','at')):
                    errors.append('stage_response_barrier_release')
            if boundaries:
                fence = boundaries[0]['fence']
                originals = [h for h in held if h['barrier_id']==fence['barrier_id']]
                if (len(originals)!=1 or any(fence.get(k)!=v for k,v in originals[0].items() if k not in ('kind','at'))
                        or fence.get('tool_call_ids') != [boundaries[0]['tool_call_id']]
                        or fence.get('completed_tool_call_ids') != fence.get('tool_call_ids')):
                    errors.append('stage_response_barrier_boundary')
                native,_ = journal(root/'evidence/agent.jsonl')
                terminals = [r.get('part',{}) for r in native if r.get('type')=='tool_use'
                    and r.get('part',{}).get('callID')==boundaries[0]['tool_call_id']]
                if (len(terminals)!=1 or terminals[0].get('sessionID') not in sessions
                        or terminals[0].get('messageID')!=boundaries[0]['message_id']
                        or terminals[0].get('state',{}).get('status')!=boundaries[0]['tool_status']):
                    errors.append('stage_native_tool_boundary')
                proof_events = [e for e in events if e['request_id']==fence.get('request_id')]
                if len(proof_events)!=1 or proof_events[0]['request_sha256']!=fence.get('request_sha256'):
                    errors.append('stage_boundary_request_original')
                else:
                    response_path = raw/proof_events[0]['response_file']
                    if (Path(proof_events[0]['response_file']).name != proof_events[0]['response_file']
                            or util.sha256_file(response_path)!=proof_events[0]['response_sha256']
                            or gateway.response_tool_ids(response_path.read_bytes())!=fence.get('tool_call_ids')):
                        errors.append('stage_boundary_response_original')
                acks = [e for e in ledger if e['kind']=='acknowledged']
                releases = [r for r in released if r['barrier_id']==fence['barrier_id']]
                if releases and (len(acks)!=1 or releases[0].get('native_message_id')!=acks[0]['native_message_id']):
                    errors.append('stage_release_without_native_ack')
        first_observed = first_transmitted = None
        for event in events:
            path = raw/event['request_file']
            if Path(event['request_file']).name != event['request_file'] or util.sha256_file(path) != event['request_sha256']:
                raise ValueError('Staged request original mismatch')
            proof = gateway.check_additional_input(util.read_json(path), expected)
            receipt = proof_by_request.get(event['request_id'])
            if receipt and (receipt['request_sha256'] != event['request_sha256'] or receipt['receipt'] != proof):
                errors.append('stage_request_proof_mismatch')
            sent = event.get('send_evidence') == 'observed_send' or event.get('provider_acknowledged') is True
            if sent and receipt is None: errors.append('stage_sent_without_input_check')
            if receipt and receipt.get('rejection'): errors.append('stage_'+receipt['rejection'])
            if not proof['locations']: continue
            if not proof['verified']: errors.append('stage_wrong_role_or_duplicate')
            if not intents or not arms: errors.append('stage_input_before_intent')
            elif (receipt is None or datetime.fromisoformat(event['started_at']).timestamp() < intents[0]['at_unix']
                  or records.index(receipt) < records.index(arms[0])):
                errors.append('stage_input_before_intent')
            if first_observed is None:
                first_observed = {'request_id': event['request_id'], 'request_sha256': event['request_sha256'],
                                  'locations': proof['locations'], 'send_evidence': event.get('send_evidence', 'unknown')}
            if sent and proof['verified'] and first_transmitted is None:
                first_transmitted = dict(first_observed, request_id=event['request_id'],
                    request_sha256=event['request_sha256'], locations=proof['locations'], send_evidence='observed_send')
        if len(intents) > 1: errors.append('stage_duplicate_intent')
        from . import staged_artifacts
        artifacts=staged_artifacts.summary(controller,(state.get('terminal') or {}).get('reason'))
        if state.get('terminal') and state['terminal'].get('checkpoints')!=artifacts:
            errors.append('stage_checkpoint_terminal_mismatch')
        post=artifacts['after-additional']
        if post.get('archive'):
            fence=post['binding']['fence']
            if not first_observed or fence.get('first_additional_request_id')!=first_observed['request_id']:
                errors.append('stage_checkpoint_before_observed_input')
            found=[b for b in barriers if b.get('kind')=='released' and b['barrier_id']==fence['barrier_id']]
            if len(found)!=1 or found[0].get('capture_complete') is not True:
                errors.append('stage_checkpoint_release_unverified')
        value = {**state, 'native_session_ids': sessions,
            'checkpoints':artifacts,
            'native_acknowledged': any(e['kind'] == 'acknowledged' for e in ledger),
            'first_observed_request': first_observed, 'first_transmitted_request': first_transmitted,
            'additional_input_reached': bool(first_transmitted) and not errors,
            'controller_ledger_sha256': util.sha256_file(controller.root/'events.jsonl'),
            'gateway_ledger_sha256': util.sha256_file(raw/'staged-input.jsonl') if (raw/'staged-input.jsonl').exists() else None,
            'issues': sorted(set(errors)), 'usage_scope': 'all requests from the original Run; never reset per stage'}
        return value, errors
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {'additional_input_reached': False, 'evidence_error_type': type(error).__name__}, ['stage_evidence_unverified']


def collect(root):
    root = Path(root)
    manifest = util.read_json(root / 'manifest.json')
    raw = root / 'usage/raw'
    starts, start_errors = journal(raw / 'started.jsonl')
    ends, end_errors = journal(raw / 'events.jsonl')
    session_id = manifest.get('run_instance_id', manifest['run_id'])
    events, issues = reconcile(starts, ends, manifest['run_id'], session_id)
    issues += start_errors + end_errors
    if (raw / 'failure.jsonl').exists():
        issues.append('gateway_failed')
    if not manifest['stop_confirmed']:
        issues.append('stop_unconfirmed')
    isolation = root / 'evidence/isolation.json'
    if not isolation.exists() or not util.read_json(isolation).get('verified'):
        issues.append('isolation_unverified')
    context = util.read_json(root / 'context.json')
    if util.sha256_file(root / 'context.json') != manifest.get('context_sha256'):
        issues.append('context_original_mismatch')
    matches, conflicts, raw_bindings = [], [], []
    source_reads = []
    prompt_reached = False
    for event in events:
        names = (event.get('request_file', ''), event.get('response_file', ''))
        if any(not name or Path(name).name != name or '\\' in name or ':' in name for name in names):
            issues.append('invalid_original_path')
            continue
        request_path, response_path = (raw / name for name in names)
        if not request_path.is_file() or util.sha256_file(request_path) != event['request_sha256']:
            issues.append('request_original_mismatch')
            continue
        if not response_path.is_file() or util.sha256_file(response_path) != event.get('response_sha256'):
            issues.append('response_original_mismatch')
        if response_path.is_file():
            parsed = gateway.parse_sse(response_path.read_bytes())
            if parsed.get('usage') != event.get('usage'):
                conflicts.append({'request_id': event['request_id'], 'raw_usage': parsed.get('usage'),
                    'journal_usage': event.get('usage'), 'response_sha256': util.sha256_file(response_path)})
                issues.append('raw_journal_usage_conflict')
            # The raw report remains authoritative for observed partial amounts;
            # a disagreement prevents exact totals and retains both alternatives.
            event['journal_usage'] = event.get('usage')
            event['usage'] = parsed.get('usage')
            event['raw_stream_done'] = parsed['stream_done']
            if parsed['parse_errors']:
                issues.append('partial_or_invalid_sse')
            if not parsed['stream_done'] or event.get('status') != 'completed':
                issues.append('stream_incomplete')
        raw_bindings.append({'request_id': event['request_id'], 'request_sha256': event['request_sha256'],
            'response_sha256': util.sha256_file(response_path) if response_path.is_file() else None,
            'run_instance_id': manifest.get('run_instance_id')})
        try:
            body = util.read_json(request_path)
        except (ValueError, UnicodeError):
            issues.append('invalid_request_original')
            continue
        messages = body.get('messages', [])
        transmitted = list(strings(messages))
        if event == events[0]:
            prompt_reached = bool(input_locations(messages, (root / 'inputs/prompt.txt').read_text(encoding='utf-8')))
        for block in context['blocks']:
            # Injection must be in the first request, not a later model/tool echo.
            locations = input_locations(messages, block['text']) if event == events[0] else []
            if locations:
                matches.append({'source': block['source'], 'block_sha256': block['sha256'],
                                'request_id': event['request_id'], 'request_file': event['request_file'],
                                'input_locations': locations})
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if msg.get('role') == 'tool' and any('/input/legacy-source/' in s for s in strings(msg)):
                source_reads.append(event['request_id'])
    reached = (True if context['method'] == 'explore' else
               {x['source'] for x in matches} == {x['source'] for x in context['blocks']})
    reached = reached and prompt_reached
    # Agent-native identifiers are kept separate from the gateway's logical session ID.
    native, _ = journal(root / 'evidence/agent.jsonl')
    native_sessions = sorted({e['sessionID'] for e in native if isinstance(e.get('sessionID'), str)})
    native_steps = sum(e.get('type') == 'step_finish' for e in native)
    if len(native_sessions) != 1 or native_steps == 0:
        issues.append('native_agent_completion_unverified')
    if native_steps > len(ends):
        issues.append('native_steps_exceed_gateway_calls')
    stages, stage_issues = staged_evidence(root, manifest, events, native_sessions)
    issues += stage_issues
    if stages is not None:
        reached = reached and stages['additional_input_reached']
        util.write_json_atomic(root/'usage/staged-input-evidence.json', stages)
    util.write_json_atomic(root / 'usage/context-evidence.json', {
        'method': context['method'], 'input_reached': reached, 'blocks': matches,
        'first_request_prompt_reached': prompt_reached,
        'source_read_request_ids': sorted(set(source_reads)),
        'limitation': 'Shows transmitted input, not model understanding or causal effect.'})
    util.write_json_atomic(root / 'usage/provenance.json', {
        'schema_version': 2, 'run_id': manifest['run_id'], 'source': 'sample2-gateway',
        'native_agent_session_ids': native_sessions,
        'native_step_count': native_steps,
        'run_instance_id': manifest.get('run_instance_id'),
        'expected_sessions': [session_id], 'inventory_complete': not issues,
        'inventory_complete_basis': {'issues': sorted(set(issues)), 'started_count': len(starts),
            'ended_count': len(ends),
            'transport': 'worker internal Docker network; sole outbound gateway',
            'stop_confirmed': manifest['stop_confirmed']},
        'raw_files': sorted(p.relative_to(root / 'usage').as_posix() for p in raw.glob('*') if p.is_file()),
        'observable': ['transmitted messages and tools', 'all gateway requests including auxiliary requests',
                       'provider token usage', 'context injection'],
        'not_observable': ['provider internals', 'unreported cache/reasoning breakdown', 'model understanding']})
    (root / 'usage/events.jsonl').write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in events),
                                           encoding='utf-8', newline='\n')
    run._normalize_usage(root, manifest['run_id'])
    path = root / 'usage/normalized.json'
    normalized = util.read_json(path)
    for key in ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'reasoning_tokens'):
        vals = [(e.get('usage') or {}).get(key) for e in events]
        known = [v for v in vals if type(v) is int and v >= 0]
        normalized['observed_' + key] = sum(known) if known else None
        normalized[key] = sum(known) if events and len(known) == len(vals) and not issues else None
    normalized['input_reached'] = reached
    if stages is not None: normalized['staged_input'] = stages
    normalized['inventory_issues'] = sorted(set(issues))
    components = [normalized['observed_input_tokens'], normalized['observed_output_tokens']]
    normalized['observed_tokens'] = sum(v for v in components if v is not None) if any(v is not None for v in components) else None
    normalized['observed_call_count'] = len(events)
    normalized.update(evidence_version=3, run_instance_id=manifest.get('run_instance_id'),
        conflicts=conflicts, raw_bindings=raw_bindings,
        execution_evidence=execution_evidence(root))
    util.write_json_atomic(path, normalized)
    # Append versioned receipts; compatibility files above remain readable by
    # existing consumers. Neither provider originals nor old archives change.
    import uuid
    version = root / 'usage/derivations' / uuid.uuid4().hex
    util.write_new_json(version / 'normalized.json', normalized)
    util.write_new_json(version / 'binding.json', {'run_id': manifest['run_id'],
        'run_instance_id': manifest.get('run_instance_id'), 'raw': raw_bindings,
        'normalized_sha256': util.sha256_file(version / 'normalized.json'),
        'manifest_sha256': util.sha256_file(root / 'manifest.json')})
    return normalized
