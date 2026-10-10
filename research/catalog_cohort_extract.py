"""Read a fixed cohort snapshot using only Python's standard library.

No model, evaluator, server, network, database write, or original-file write.
CSV empty fields represent unreported/not applicable values, never zero.
"""
import argparse
from collections import Counter
from contextlib import closing
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3


TOKEN_FIELDS = ('input_tokens', 'output_tokens', 'cache_read_tokens',
                'cache_write_tokens', 'reasoning_tokens')
OTLP_FIELDS = dict(zip(TOKEN_FIELDS, ('gen_ai.usage.input_tokens',
    'gen_ai.usage.output_tokens', 'sample2.cache_read_tokens',
    'sample2.cache_write_tokens', 'sample2.reasoning_tokens')))


def native(path):
    value = str(Path(path).resolve())
    return Path('\\\\?\\' + value) if os.name == 'nt' and not value.startswith('\\\\?\\') else Path(value)


def member(root, relative):
    p = PurePosixPath(relative)
    if p.is_absolute() or '..' in p.parts or not p.parts or ':' in relative or '\\' in relative:
        raise ValueError('Unsafe relative path: ' + relative)
    return root.joinpath(*p.parts)


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def lines(path):
    with path.open(encoding='utf-8-sig') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def dump(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def csv_value(value):
    if value is None:
        return ''
    if isinstance(value, (bool, list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    return value


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: csv_value(v) for k, v in row.items()})
    return fields


def attrs(items):
    result = {}
    for item in items:
        key, v = item['key'], item['value']
        if key in result:
            raise ValueError('Duplicate OTLP attribute: ' + key)
        result[key] = int(v['intValue']) if 'intValue' in v else v.get('stringValue')
    return result


def provider_usage(value):
    if value is None:
        return {k: None for k in (*TOKEN_FIELDS, 'total_tokens')}
    inp = value.get('prompt_tokens_details') or {}
    out = value.get('completion_tokens_details') or {}
    return dict(input_tokens=value.get('prompt_tokens'), output_tokens=value.get('completion_tokens'),
        total_tokens=value.get('total_tokens'),
        cache_read_tokens=inp.get('cached_tokens', value.get('prompt_cache_hit_tokens')),
        cache_write_tokens=inp.get('cache_write_tokens'), reasoning_tokens=out.get('reasoning_tokens'))


def sse(path):
    usage, done, models = None, False, set()
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            if not line.startswith('data:'):
                continue
            payload = line[5:].strip()
            if payload == '[DONE]':
                done = True
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue  # Non-success bodies remain available in the original response.
            if obj.get('model'):
                models.add(obj['model'])
            if obj.get('usage'):
                usage = obj['usage']
    return usage, done, sorted(models)


def extract(root, out):
    snapshot = read(root / 'SNAPSHOT.json')
    inventory = snapshot['original_inventory']
    errors, counts = [], Counter()
    limitations, discrepancies = [], []
    declared_unsealed = {
        item['run_id'] if isinstance(item, dict) else item
        for item in snapshot.get('unsealed_stopped_runs', [])
    }

    def check(ok, kind, run_id=None, detail=None):
        counts[kind] += 1
        if not ok:
            errors.append({'check': kind, 'run_id': run_id, 'detail': detail})

    by_path = {f['path']: f for f in inventory}
    check(len(by_path) == len(inventory), 'unique_snapshot_paths')
    for item in inventory:
        path = member(root, item['path'])
        check(path.is_file() and path.stat().st_size == item['bytes'] and sha(path) == item['sha256'],
              'snapshot_file_hash', detail=item['path'])
    planpath = member(root, snapshot['plan_path'])
    check(sha(planpath) == snapshot['plan_sha256'], 'plan_hash')
    plan = read(planpath)
    slots = plan['slots']
    check(len(slots) == snapshot['assigned_slots'], 'assigned_slot_count')
    selection = set(snapshot['selected_runs'])
    check(declared_unsealed <= selection, 'unsealed_runs_within_selection')
    check(len(selection) == len(snapshot['selected_runs']), 'unique_selected_runs')
    check(selection == {s['run_id'] for s in slots if s['block'] <= snapshot['through_block']},
          'selected_prefix')
    obs = {}
    for block in range(1, snapshot['through_block'] + 1):
        doc = read(member(root, f"{plan['runs_dir']}/_control/observations-pair-{block:03d}.json"))
        check(doc['plan_sha256'] == snapshot['plan_sha256'], 'observation_plan_hash')
        for r in doc['runs']:
            check(r['run_id'] not in obs, 'unique_observation_run', r['run_id'])
            obs[r['run_id']] = r
    check(set(obs) == selection, 'observation_selection')
    ledger, run_rows, calls, requirements, attempts, actions, run_checks = [], [], [], [], [], [], []
    req_ids = ['R-%03d' % n for n in range(1, plan['quality']['requirements'] + 1)]
    for slot in slots:
        rid = slot['run_id']
        base = {'run_id': rid, 'block': slot['block'], 'position': slot['position'], 'condition': slot['condition']}
        ledger_row = {**base, 'in_snapshot': rid in selection, 'execution_state': None,
                      'source': 'SNAPSHOT.json selected_runs and frozen plan slots'}
        ledger.append(ledger_row)
        if rid not in selection:
            continue
        prefix = f"{plan['runs_dir']}/{rid}"
        rr = member(root, prefix)
        manifest = read(rr / 'manifest.json')
        is_unsealed = rid in declared_unsealed
        norm_present = (rr / 'usage/normalized.json').is_file()
        norm = read(rr / 'usage/normalized.json') if norm_present else {}
        seal_present = member(root, f"{plan['runs_dir']}/_control/{rid}.seal.json").is_file()
        check(seal_present or is_unsealed, 'acquisition_seal_or_disclosure', rid)
        check(norm_present or is_unsealed, 'normalization_or_disclosure', rid)
        if is_unsealed:
            check(not seal_present and manifest.get('end_reason') == 'operator_stop' and
                  manifest.get('submission_fixed') is False and not (rr/'evaluations/index.jsonl').exists(),
                  'declared_unsealed_stopped_state', rid)
            limitations.append({'kind':'acquisition_seal_absent', 'run_id':rid,
                'detail':'Snapshot preserves current bytes; no acquisition seal is fabricated.'})
        if not norm_present:
            limitations.append({'kind':'normalization_absent', 'run_id':rid,
                'detail':'Raw reported partial sums are retained; Run totals and usage_complete remain unknown.'})
        observation = obs[rid]
        check(observation['case'] == slot, 'observation_slot', rid)
        check(manifest['run_id'] == observation['run_id'] == rid and
              (not norm_present or norm['run_id'] == rid), 'run_identity', rid)
        check(manifest['intervention_id'] == slot['condition'], 'condition_identity', rid)
        if is_unsealed:
            check(manifest.get('stop_confirmed') is True, 'unsealed_run_stopped', rid)
            if manifest.get('submission_fixed') is not True:
                limitations.append({'kind':'submission_not_fixed', 'run_id':rid,
                    'detail':'No fixed generated artifact; no new scoring is performed.'})
        else:
            check(manifest.get('stop_confirmed') is True and manifest.get('submission_fixed') is True,
                  'stopped_and_fixed', rid)
        starts, ends = lines(rr/'usage/raw/started.jsonl'), lines(rr/'usage/raw/events.jsonl')
        e_by = {e['request_id']: e for e in ends}
        check(len(e_by) == len(ends) and len({s['request_id'] for s in starts}) == len(starts),
              'unique_request_ids', rid)
        check({s['request_id'] for s in starts} == set(e_by), 'request_inventory', rid)
        these_calls = []
        for number, start in enumerate(starts, 1):
            e = e_by.get(start['request_id'], {})
            reqrel, resrel = 'usage/raw/' + start['request_file'], 'usage/raw/' + start['response_file']
            check(by_path.get(prefix+'/'+reqrel, {}).get('sha256') == start.get('request_sha256'),
                  'request_recorded_hash', rid, start['request_id'])
            check(by_path.get(prefix+'/'+resrel, {}).get('sha256') == e.get('response_sha256'),
                  'response_recorded_hash', rid, start['request_id'])
            original, done, models = sse(member(rr, resrel))
            usage = provider_usage(original)
            check(original == e.get('native_usage'), 'sse_native_usage', rid, start['request_id'])
            check(all(usage[k] == (e.get('usage') or {}).get(k) for k in TOKEN_FIELDS),
                  'sse_normalized_event_usage', rid, start['request_id'])
            if original != e.get('native_usage') or any(usage[k] != (e.get('usage') or {}).get(k) for k in TOKEN_FIELDS):
                discrepancies.append({'kind':'sse_usage_disagrees_with_terminal_event', 'run_id':rid,
                    'request_id':start['request_id'], 'sse_usage':usage, 'terminal_event_usage':e.get('usage'),
                    'terminal_event_status':e.get('status'), 'sse_done':done,
                    'sources':[prefix+'/'+resrel,prefix+'/usage/raw/events.jsonl'],
                    'resolution':'SSE-reported partial values retained without declaring Run usage complete.'})
            if usage['input_tokens'] is not None and usage['output_tokens'] is not None:
                check(usage['total_tokens'] == usage['input_tokens'] + usage['output_tokens'],
                      'provider_total_arithmetic', rid, start['request_id'])
            check(all(v is None or type(v) is int and v >= 0 for v in usage.values()), 'token_value_domain', rid)
            check(e.get('run_id') == rid and e.get('session_id') == manifest.get('run_instance_id'),
                  'request_run_identity', rid, start['request_id'])
            call = {**base, 'call_index': number, 'request_id': start['request_id'],
                    'run_instance_id': manifest['run_instance_id'], 'status': e.get('status'),
                    'http_status': e.get('http_status'), 'started_at': e.get('started_at'),
                    'ended_at': e.get('ended_at'), 'response_models': models, 'stream_done': done,
                    **usage, 'usage_reported': original is not None,
                    'request_file': prefix+'/'+reqrel, 'response_file': prefix+'/'+resrel,
                    'request_sha256': start.get('request_sha256'), 'response_sha256': e.get('response_sha256')}
            these_calls.append(call)
        calls.extend(these_calls)
        known = {}
        for field in TOKEN_FIELDS:
            values = [r[field] for r in these_calls if r[field] is not None]
            known[field] = sum(values) if values else None
            complete = known[field] if values and len(values) == len(starts) and norm.get('usage_complete') else None
            if norm_present:
                check(norm.get('observed_'+field) == known[field] and norm.get(field) == complete,
                      'raw_to_normalized_'+field, rid)
        observed_parts = [known[k] for k in ('input_tokens','output_tokens') if known[k] is not None]
        known_total = sum(observed_parts) if observed_parts else None
        if norm_present:
            check(known_total == norm['observed_tokens'], 'observed_total', rid)
            check(norm['total_tokens'] == (known_total if norm['usage_complete'] else None), 'complete_total', rid)
            if known_total != norm['observed_tokens']:
                discrepancies.append({'kind':'sse_partial_sum_disagrees_with_saved_normalization', 'run_id':rid,
                    'sse_observed_tokens':known_total, 'normalized_observed_tokens':norm['observed_tokens'],
                    'sources':[prefix+'/usage/raw/',prefix+'/usage/normalized.json'],
                    'resolution':'Both values preserved; observed_tokens in runs.csv uses raw SSE, total_tokens stays unknown when incomplete.'})
        saved_tokens = observation.get('tokens') or {}
        check(saved_tokens.get('known_total_tokens') == known_total and saved_tokens.get('total_tokens') == norm.get('total_tokens'),
              'observation_tokens', rid)
        check(len(observation.get('calls', [])) == len(these_calls) and
              [c['request_id'] for c in observation.get('calls', [])] == [c['request_id'] for c in these_calls],
              'observation_call_inventory', rid)
        for raw_call, saved_call in zip(these_calls, observation.get('calls', [])):
            check(all(raw_call[k] == saved_call.get(k) for k in ('input_tokens','output_tokens','status','http_status')),
                  'observation_call_usage', rid, raw_call['request_id'])
        response_observed = any(c['status'] == 'completed' and c['response_models'] for c in these_calls)
        if response_observed and manifest.get('model_called') is not True:
            discrepancies.append({'kind':'manifest_model_called_disagrees_with_raw_responses', 'run_id':rid,
                'manifest_value':manifest.get('model_called'), 'observed_completed_responses':
                    sum(c['status'] == 'completed' and bool(c['response_models']) for c in these_calls),
                'sources':[prefix+'/manifest.json',prefix+'/usage/raw/events.jsonl'],
                'resolution':'Original flag retained; model_response_observed separately records raw response evidence.'})
        # Verify any gateway SQLite as an immutable read-only file, never checkpoint it.
        dbpath = rr / 'telemetry/monitor.db'
        telemetry_paths = (dbpath,rr/'telemetry/gateway.otlp.json',rr/'telemetry-link.json')
        telemetry_present = all(p.is_file() for p in telemetry_paths)
        integrity = None
        check(telemetry_present or is_unsealed, 'telemetry_or_disclosure', rid)
        if not telemetry_present:
            limitations.append({'kind':'telemetry_incomplete', 'run_id':rid,
                'missing_files':[p.relative_to(root).as_posix() for p in telemetry_paths if not p.is_file()]})
        if dbpath.is_file():
            check(not any(Path(str(dbpath)+s).exists() for s in ('-wal','-shm','-journal')), 'sealed_sqlite', rid)
            # Remove the Windows extended prefix only for SQLite's file URI syntax.
            regular = Path(str(dbpath)[4:]) if str(dbpath).startswith('\\\\?\\') else dbpath
            with closing(sqlite3.connect(regular.as_uri()+'?mode=ro&immutable=1', uri=True)) as db:
                db.execute('PRAGMA query_only=ON')
                integrity = [r[0] for r in db.execute('PRAGMA integrity_check')]
                stored = [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM raw_records ORDER BY id')]
            check(integrity == ['ok'], 'sqlite_integrity', rid)
            if telemetry_paths[1].is_file():
                check(stored == [read(telemetry_paths[1])], 'sqlite_exact_otlp', rid)
        if telemetry_paths[1].is_file():
            otlp = read(telemetry_paths[1])
            spans = []
            for resource in otlp['resourceSpans']:
                identity = attrs(resource['resource']['attributes'])
                check(identity.get('run.id') == rid and identity.get('sample2.run_instance_id') == manifest['run_instance_id'],
                      'otlp_run_identity', rid)
                for scope in resource['scopeSpans']:
                    spans.extend(attrs(s['attributes']) for s in scope['spans'])
            span_by = {s.get('sample2.request.id'): s for s in spans}
            check(len(span_by) == len(spans) and set(span_by) == set(e_by), 'otlp_request_inventory', rid)
            for call in these_calls:
                span = span_by.get(call['request_id'], {})
                check(all(call[f] == span.get(k) for f,k in OTLP_FIELDS.items()), 'otlp_request_usage', rid, call['request_id'])
        if telemetry_paths[2].is_file():
            link = read(telemetry_paths[2])
            check(link.get('verified') is True and link.get('request_count') == len(starts), 'telemetry_receipt', rid)
        index_present = (rr/'evaluations/index.jsonl').is_file()
        check(index_present or is_unsealed, 'evaluation_index_or_disclosure', rid)
        index = lines(rr/'evaluations/index.jsonl') if index_present else []
        if not index_present:
            limitations.append({'kind':'evaluation_not_attempted', 'run_id':rid,
                'detail':'All requirement judgements, numeric quality and all-pass remain unknown.'})
        evaluation, last = {}, index[-1] if index else {}
        for entry in index:
            erel = entry['directory']+'/evaluation.json'
            ev = read(member(rr, erel))
            check(by_path.get(prefix+'/'+erel, {}).get('sha256') == entry.get('evaluation_sha256'),
                  'evaluation_recorded_hash', rid, entry['sequence'])
            check(entry['run_id'] == rid and ev['evaluationId'] == entry['evaluation_id'] and
                  ev['artifactSha256'] == entry['artifact_sha256_outer'], 'evaluation_identity', rid, entry['sequence'])
            attempts.append({**base, 'sequence':entry['sequence'], 'adopted':entry.get('adopted'),
                'scoring_state':entry['scoring_state'], 'verdict':entry.get('verdict'), 'quality':entry.get('quality'),
                'evaluation_version':entry.get('evaluation_version'), 'evaluator_sha256':entry.get('evaluator_sha256'),
                'spec_sha256':entry.get('spec_sha256'), 'artifact_sha256':entry.get('artifact_sha256_outer'),
                'started_at':ev.get('startedAt'), 'finished_at':ev.get('finishedAt'),
                'browser_coverage':ev.get('browserCartCoverage'), 'evaluator_faults':ev.get('evaluatorFaults'),
                'source':prefix+'/'+erel})
            evaluation = ev
        req_by = {r['id']:r for r in evaluation.get('requirements', [])}
        check(len(req_by) == len(evaluation.get('requirements', [])) and set(req_by) <= set(req_ids), 'requirement_ids', rid)
        check({k:v['judgement'] for k,v in req_by.items()} ==
              {r['id']:r['judgement'] for r in observation.get('requirements', [])}, 'observation_requirements', rid)
        complete_quality = bool(last.get('adopted') and last.get('scoring_state') == 'scored' and
                                last.get('research_status') == 'complete' and not evaluation.get('evaluatorFaults'))
        quality = last.get('quality') if complete_quality else None
        failed_ids = [k for k,v in req_by.items() if v['judgement'] == 'fail']
        all_pass = bool(len(req_by) == len(req_ids) and all(r['judgement']=='pass' for r in req_by.values()))
        outcome = 0 if failed_ids else 1 if complete_quality and all_pass and last.get('verdict') == 'pass' else None
        for key in req_ids if index_present else []:
            item = req_by.get(key, {})
            requirements.append({**base, 'requirement_id':key, 'judgement':item.get('judgement'),
                'title':item.get('title'), 'severity':item.get('severity'), 'failed_checks':item.get('failedChecks'),
                'evaluation_sequence':last.get('sequence'), 'evaluation_complete':complete_quality,
                'source':prefix+'/'+last['directory']+'/evaluation.json' if last else None})
        check(observation['row']['quality'] == quality and observation['row']['scoring']['sequence'] == last.get('sequence'),
              'observation_quality', rid)
        native_events = lines(rr/'evidence/agent.jsonl')
        for line_number, event in enumerate(native_events, 1):
            if event.get('type') != 'tool_use':
                continue
            part = event['part']; state = part.get('state', {}); inputs = state.get('input', {})
            output = state.get('output', '')
            actions.append({**base,'tool_call_id':part.get('callID'), 'tool':part.get('tool'),
                'status':state.get('status'), 'timestamp':event.get('timestamp'), 'session_id':event.get('sessionID'),
                'file_path':inputs.get('filePath'), 'command':inputs.get('command'), 'input_json':inputs,
                'output_utf8_bytes':len(output.encode('utf-8')),
                'output_sha256':hashlib.sha256(output.encode('utf-8')).hexdigest(),
                'source':prefix+'/evidence/agent.jsonl:'+str(line_number)})
        ledger_row['execution_state'] = manifest.get('end_reason')
        run_rows.append({**base, 'run_instance_id':manifest['run_instance_id'],
            'started_at':manifest.get('started_at'), 'ended_at':manifest.get('ended_at'),
            'duration_seconds':manifest.get('duration_seconds'), 'execution_state':manifest.get('end_reason'),
            'stop_confirmed':manifest.get('stop_confirmed'), 'submission_fixed':manifest.get('submission_fixed'),
            'usage_complete':norm.get('usage_complete'), 'request_count':len(starts),
            'requests_with_usage':sum(c['usage_reported'] for c in these_calls),
            **{k:norm.get(k) for k in (*TOKEN_FIELDS,'total_tokens')},
            **{'observed_'+k:v for k,v in known.items()}, 'observed_tokens':known_total,
            'normalized_observed_tokens':norm.get('observed_tokens'),
            'scoring_state':last.get('scoring_state'), 'evaluation_sequence':last.get('sequence'),
            'evaluation_attempts':len(index), 'evaluation_complete':complete_quality,
            'quality':quality, 'saved_verdict':last.get('verdict'), 'all_requirements_pass':outcome,
            'known_failed_requirements':failed_ids, 'passed_requirements':sum(r['judgement']=='pass' for r in req_by.values()),
            'blocked_requirements':sum(r['judgement']=='blocked' for r in req_by.values()),
            'human_review':observation.get('human_review'), 'evaluator_faults':evaluation.get('evaluatorFaults'),
            'manifest_file':prefix+'/manifest.json', 'usage_file':prefix+'/usage/normalized.json' if norm_present else None,
            'acquisition_seal_present':seal_present, 'normalization_present':norm_present,
            'telemetry_present':telemetry_present, 'evaluation_index_present':index_present,
            'model_called_manifest':manifest.get('model_called'), 'model_response_observed':response_observed})
        if not index_present:
            run_rows[-1].update(scoring_state=observation['row']['scoring']['state'],
                                passed_requirements=None, blocked_requirements=None)
        run_checks.append({'run_id':rid,'requests':len(starts),'sqlite_integrity':integrity,
                           'measurement_limitations':[v for v in limitations if v['run_id']==rid],
                           'record_discrepancies':[v for v in discrepancies if v['run_id']==rid],
                           'failures':[e for e in errors if e['run_id']==rid]})
        print('Read', rid, flush=True)
    tables = {'ledger.csv':ledger,'runs.csv':run_rows,'calls.csv':calls,'requirements.csv':requirements,
              'evaluation_attempts.csv':attempts,'actions.csv':actions}
    fields = {name:write_csv(out/name, rows) for name,rows in tables.items()}
    dictionary = {
        'format': {'encoding':'UTF-8 with BOM','null':'空欄は未報告・未測定・非該当。0に置換しない。',
                   'boolean':'true / false','nested_values':'配列・オブジェクトはJSON文字列。',
                   'time':'原記録のISO 8601日時。timestampは原記録のUnixミリ秒。'},
        'tables': {k:{'rows':len(tables[k]),'columns':v} for k,v in fields.items()},
        'column_notes': {
            'run_id':'割付された1回の実行の識別子。','block':'隣接して実行する2条件の割付組番号。',
            'position':'割付組内の実行順（1または2）。','condition':'catalog-compact / catalog-expanded の保存済み条件名。',
            'in_snapshot':'固定範囲に含まれるか。falseは未実行を意味しない。',
            'execution_state':'実行manifestのend_reason。評価結果とは別。',
            'run_instance_id':'実際に開始された実行インスタンスの識別子。',
            'duration_seconds':'実行制御開始から停止確認まで。準備と停止処理を含み、評価と共有、後段のネットワーク後始末は含まない。',
            'usage_complete':'保存済みusageにおける呼出し一覧と入力・出力tokenの完全性。任意内訳の報告有無とは別。',
            'request_count':'開始台帳に記録された全要求数。失敗要求も含む。',
            'requests_with_usage':'応答SSEにusageが記録された要求数。',
            'input_tokens':'提供者が報告した入力token。キャッシュ読み取り分を内包する。',
            'output_tokens':'提供者が報告した出力token。推論token内訳を別途加算しない。',
            'total_tokens':'完全な実行における入力tokenと出力tokenの和。欠測があれば空欄。',
            'observed_tokens':'報告された入力tokenと出力tokenの部分和。真の総消費量が未確定でも保持する。',
            'observed_*':'その内訳の報告済み値の部分和。全要求で未報告なら空欄。',
            'cache_read_tokens':'入力tokenのうちキャッシュ読み取りとして報告された内訳。',
            'cache_write_tokens':'キャッシュ書き込みとして報告された内訳。未報告は空欄。',
            'reasoning_tokens':'出力tokenのうち推論として報告された内訳。',
            'quality':'採用され、評価範囲が完了した最新評価の数値品質点。全29要件の合格数から計算される。',
            'all_requirements_pass':'既知の要件失敗があれば0。評価完了かつ全要件合格なら1。それ以外は空欄。',
            'evaluation_complete':'最新評価が採用済み、scored、research_status complete、評価側障害なし。',
            'saved_verdict':'最新評価indexに保存されたverdict。数値品質の有無と独立。',
            'known_failed_requirements':'最新評価でfailと記録された要件IDの配列。',
            'human_review':'既存観察JSONの人間評価状態。今回の読取器が人間評価を実施したものではない。',
            'judgement':'保存済み要件判定pass/fail/blocked/error等。要件記録がなければ空欄。',
            'scoring_state':'最新評価indexの採点状態。evaluator_faultでも保存済み個別失敗は保持。',
            'evaluation_sequence':'同じ実行内の評価試行番号。','adopted':'評価indexの採用状態。',
            'call_index':'開始台帳の記録順。','usage_reported':'SSEにusageオブジェクトが存在したか。',
            'response_models':'応答SSEが報告したmodel名一覧。','stream_done':'SSEの[DONE]記録有無。',
            'output_utf8_bytes':'ツール出力文字列をUTF-8化したバイト数。token数ではない。',
            'source':'ZIP内の原記録への相対参照。末尾の:数値は行番号。',
            '*_sha256':'原記録または明示した文字列バイトのSHA-256。',
            'evaluator_faults':'保存済み評価側障害の配列。製品要件失敗と別に保持。'},
        'scope':{'through_block':snapshot['through_block'],'selected_run_count':len(selection),
                 'assigned_slots':len(slots),'dispatched_outside_snapshot':snapshot.get('dispatched_outside_snapshot',[]),
                 'rule':'選択範囲外のjournal項目はCSVの実行結果に追加しない。全割付はledgerに保持。'},
        'execution':'保存済みデータの読み取りと整合検証のみ。モデル呼出し・成果物評価の再実行は行わない。'}
    dictionary['column_notes'].update({
        'started_at':'原記録に保存された開始日時。表により実行・要求・評価試行の開始を表す。',
        'ended_at':'原記録に保存された実行または要求の終了日時。',
        'finished_at':'評価JSONに保存された評価の終了日時。',
        'stop_confirmed':'実行manifestの停止確認結果。',
        'submission_fixed':'実行manifestの成果物固定状態。',
        'evaluation_attempts':'保存済み評価indexの試行数。',
        'passed_requirements':'最新評価のpass要件数。',
        'blocked_requirements':'最新評価のblocked要件数。',
        'manifest_file':'実行manifestへのsnapshot相対パス。',
        'usage_file':'正規化済みusageへのsnapshot相対パス。',
        'request_id':'gatewayの要求識別子。',
        'status':'要求またはツール操作に記録された完了・失敗等の状態。',
        'http_status':'提供者HTTP応答の状態コード。応答未取得では空欄。',
        'request_file':'要求JSONへのsnapshot相対パス。',
        'response_file':'応答SSEへのsnapshot相対パス。',
        'requirement_id':'要件台帳の要件ID。',
        'title':'保存済み要件の名称。',
        'severity':'保存済み要件の重大度。',
        'failed_checks':'保存済み要件でpass以外となった検査ID。blockedやerrorも含まれ得る。',
        'sequence':'同じ実行内の評価試行番号。',
        'verdict':'各評価試行のindexに保存された全体判定。',
        'evaluation_version':'各評価試行の評価仕様版。',
        'evaluator_sha256':'保存済み評価器バイナリのSHA-256識別値。',
        'spec_sha256':'評価に使用した要件台帳のSHA-256識別値。',
        'artifact_sha256':'評価対象成果物の保存済みSHA-256識別値。',
        'browser_coverage':'評価JSONに保存されたブラウザー観測範囲の状態。',
        'tool_call_id':'agentのツール操作識別子。',
        'tool':'agentが使用したツール名。',
        'timestamp':'agentイベントに記録されたUnixミリ秒。',
        'session_id':'agentのネイティブ会話識別子。gatewayのrun_instance_idとは別。',
        'file_path':'ツール入力のfilePath。該当入力がなければ空欄。',
        'command':'ツール入力のcommand。該当入力がなければ空欄。',
        'input_json':'ツール入力の全オブジェクトをJSON文字列で保持。',
        'request_sha256':'要求JSONファイルのSHA-256。',
        'response_sha256':'応答SSEファイルのSHA-256。',
        'output_sha256':'ツール出力文字列をUTF-8化したバイト列のSHA-256。'})
    dictionary['column_notes'].update({
        'acquisition_seal_present':'採取時の封印ファイルの有無。後日のsnapshotハッシュ作成とは別。',
        'normalization_present':'保存済み正規化使用量ファイルの有無。原応答からの部分和とは別。',
        'telemetry_present':'gateway SQLite・OTLP・照合票の3ファイルがすべて存在するか。',
        'evaluation_index_present':'保存済み評価試行indexの有無。無ければ要件判定を補わない。',
        'model_called_manifest':'原manifestのmodel_called値。原応答と矛盾する場合も書き換えない。',
        'model_response_observed':'原要求に対応するcompleted応答でmodel名を観測したか。manifest値とは独立。',
        'normalized_observed_tokens':'原正規化ファイルに保存された既知使用量。原SSEの部分和observed_tokensと異なる場合もそのまま保持。'})
    dictionary['absent_evaluation'] = '評価indexがない実行では要件行を合成しない。runs.csvに実行を保持し、qualityとall_requirements_passは空欄。'
    for field in TOKEN_FIELDS:
        dictionary['column_notes']['observed_'+field] = '報告済み値の部分和。全要求で未報告なら空欄。 '+dictionary['column_notes'][field]
    dictionary['quality_in_attempts'] = 'evaluation_attempts.csvのqualityは各試行indexの保存値。runs.csvのqualityは採用・完了条件を満たす最新値。'
    dictionary['undocumented_columns'] = sorted({c for cols in fields.values() for c in cols} - set(dictionary['column_notes']))
    dump(out/'data-dictionary.json',dictionary)
    verify = {'schema_version':1,'checked_at_utc':datetime.now(timezone.utc).isoformat(),
        'snapshot_sha256':sha(root/'SNAPSHOT.json'),'plan_sha256':snapshot['plan_sha256'],
        'reader_sha256':sha(Path(__file__)),
        'verified':not errors,'checks':dict(counts),'errors':errors,'runs':run_checks,
        'measurement_limitations':limitations,'record_discrepancies':discrepancies,
        'source_records_consistent':not discrepancies,
        'verification_meaning':'Present evidence passed integrity checks; declared absent measurements and source-record discrepancies remain explicitly listed. This is not full measurement or quality acceptance.',
        'counts':{k:len(v) for k,v in tables.items()},'model_called':False,'evaluator_called':False,
        'database_mode':'mode=ro&immutable=1; PRAGMA query_only=ON',
        'scope':'snapshot SHA, identities, native SSE usage, normalized totals, saved observations, SQLite raw_records/OTLP, saved evaluation records; no new quality judgement',
        'output_hashes':{p.name:sha(p) for p in out.iterdir() if p.is_file()}}
    dump(out/'verify.json',verify)
    return verify


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a = p.parse_args()
    root,out = native(a.root),native(a.out)
    if out.exists() or out == root or out.is_relative_to(root):
        raise ValueError('Output must be a new directory outside the snapshot.')
    out.mkdir(parents=True)
    result = extract(root,out)
    print(json.dumps({'verified':result['verified'],'counts':result['counts'],'errors':len(result['errors'])}))
    raise SystemExit(0 if result['verified'] else 1)


if __name__ == '__main__':
    main()
