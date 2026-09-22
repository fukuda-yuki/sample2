"""Synthetic request fixtures; no provider, agent, evaluator or clock changes."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from research.catalog_allocation_review import sha256, write_new
from research.catalog_identity import normalize_date, object_hash, compare_initial, RULE


def body(day='Sun Sep 20 2026'):
    return {'model': 'deepseek-v4.1-flash', 'stream': True, 'temperature': 1,
            'messages': [{'role': 'system', 'content': (
                'Fixed instructions.\nHere is some useful information about the environment you are running in:\n'
                '<env>\n  Working directory: /workspace\n  Workspace root folder: /\n'
                "  Is directory a git repo: no\n  Platform: linux\n  Today's date: " + day +
                '\n</env>\nFixed skills and tool instructions.')},
                {'role': 'user', 'content': 'Fixed task.\nPACKET'}],
            'tools': [{'type': 'function', 'function': {'name': 'read', 'description': 'Read fixed files'}}]}


def save_request(root, value):
    import json
    root = Path(root)
    path = root / 'usage/raw/first.request.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')
    (path.parent / 'started.jsonl').write_text(json.dumps({'request_id': 'synthetic-request',
        'request_file': path.name, 'request_sha256': sha256(path), 'response_file': 'first.response.sse'}) + '\n', encoding='utf-8')


def run_input(root, day):
    root = Path(root)
    write_new(root / 'condition.json', {'intervention': {'append_source_packet': True}})
    write_new(root / 'state/catalog-access.json', {'verified': True, 'files': {'source': 'fixed'}, 'mode': 'read-only'})
    packet = root / 'inputs/catalog-derived/raw-first.txt'
    packet.parent.mkdir(parents=True)
    packet.write_bytes(b'PACKET')
    (root / 'inputs/prompt.txt').write_bytes(b'Fixed task.\nPACKET')
    save_request(root, body(day))


class IdentityTests(unittest.TestCase):
    def test_same_day_and_different_day_preserve_original_objects(self):
        for day in ('Sun Sep 20 2026', 'Tue Sep 22 2026'):
            first, second = body(), body(day)
            originals = deepcopy((first, second))
            a, ad = normalize_date(first); b, bd = normalize_date(second)
            self.assertEqual(a, b)
            self.assertEqual((first, second), originals)
            self.assertEqual(bd['text'], day)

    def test_month_year_and_leap_day_use_the_same_calendar_rule(self):
        for first, second in [('Wed Sep 30 2026', 'Thu Oct 01 2026'),
                              ('Thu Dec 31 2026', 'Fri Jan 01 2027'),
                              ('Tue Feb 29 2028', 'Wed Mar 01 2028')]:
            self.assertEqual(normalize_date(body(first))[0], normalize_date(body(second))[0])

    def test_invalid_calendar_weekday_format_and_pre_normalized_marker_rejected(self):
        for value in ('Mon Sep 20 2026', 'Sun Sep 31 2026', 'Sun Feb 29 2026',
                      '2026-09-20', 'Sun Sep 1 2026', 'Sun Sep 20 26',
                      '<OPENCODE_AUTOMATIC_DATE>', 'Sun Sep 20 2026 extra'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_date(body(value))

    def test_missing_duplicate_moved_date_and_environment_fields_rejected(self):
        original = body()['messages'][0]['content']
        for text in (original.replace("  Today's date: Sun Sep 20 2026\n", ''),
                     original.replace('</env>', "  Today's date: Sun Sep 20 2026\n</env>"),
                     original.replace('<env>', '<env>\n<env>'),
                     original.replace('  Platform: linux\n', ''),
                     original.replace('  Platform: linux\n', '  Unknown: linux\n'),
                     original.replace('  Platform: linux\n', '').replace('</env>', '  Platform: linux\n</env>')):
            case = body(); case['messages'][0]['content'] = text
            with self.subTest(text=text), self.assertRaises(ValueError):
                normalize_date(case)

    def test_wrong_role_position_duplicate_system_or_structured_content_rejected(self):
        cases = []
        x=body(); x['messages'][0]['role']='user'; cases.append(x)
        x=body(); x['messages'].reverse(); cases.append(x)
        x=body(); x['messages'].append(deepcopy(x['messages'][0])); cases.append(x)
        x=body(); x['messages'][0]['content']=[{'type':'text','text':x['messages'][0]['content']}]; cases.append(x)
        for case in cases:
            with self.assertRaises(ValueError): normalize_date(case)

    def test_non_date_system_task_tool_and_parameter_changes_remain_visible(self):
        base = normalize_date(body())[0]
        edits = [lambda b: b['messages'][0].update(content=b['messages'][0]['content'].replace('Fixed instructions.', 'Different instruction.')),
                 lambda b: b['messages'][1].update(content='Different task.\nPACKET'),
                 lambda b: b['tools'][0]['function'].update(description='Other files'),
                 lambda b: b.update(temperature=0),
                 lambda b: b['messages'][0].update(content=b['messages'][0]['content'].replace('/workspace', '/other'))]
        for edit in edits:
            case = body('Tue Sep 22 2026'); edit(case)
            self.assertNotEqual(base, normalize_date(case)[0])

    def test_matching_dates_in_user_tool_and_source_text_are_never_masked(self):
        for role in ('user', 'tool', 'assistant'):
            first, second = body(), body('Tue Sep 22 2026')
            first['messages'].append({'role':role,'content':"Today's date: Sun Sep 20 2026"})
            second['messages'].append({'role':role,'content':"Today's date: Tue Sep 22 2026"})
            self.assertNotEqual(normalize_date(first)[0], normalize_date(second)[0])

    def test_raw_and_normalized_results_and_hash_names_are_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            a,b=Path(temp)/'actual',Path(temp)/'baseline'
            run_input(a,'Tue Sep 22 2026'); run_input(b,'Sun Sep 20 2026')
            before=(a/'usage/raw/first.request.json').read_bytes()
            old=compare_initial(a,b,{})
            new=compare_initial(a,b,{'date_revision':{'rule':RULE}})
            self.assertFalse(old['matches']); self.assertFalse(new['raw_common_equal'])
            self.assertTrue(new['normalized_equal']); self.assertTrue(new['matches'])
            self.assertNotEqual(new['actual_common_object_sha256'],new['baseline_common_object_sha256'])
            self.assertEqual(new['actual_normalized_object_sha256'],new['baseline_normalized_object_sha256'])
            self.assertEqual(new['actual_request']['original_file_sha256'],sha256(a/'usage/raw/first.request.json'))
            self.assertEqual(before,(a/'usage/raw/first.request.json').read_bytes())

    def test_source_packet_and_access_changes_cannot_be_hidden(self):
        with tempfile.TemporaryDirectory() as temp:
            a,b=Path(temp)/'actual',Path(temp)/'baseline'
            run_input(a,'Tue Sep 22 2026'); run_input(b,'Sun Sep 20 2026')
            plan={'date_revision':{'rule':RULE}}
            altered=body('Tue Sep 22 2026'); altered['messages'][1]['content']='Fixed task.\nOTHER'
            save_request(a,altered); (a/'inputs/catalog-derived/raw-first.txt').write_bytes(b'OTHER')
            self.assertFalse(compare_initial(a,b,plan)['matches'])
            save_request(a,body('Tue Sep 22 2026')); (a/'inputs/catalog-derived/raw-first.txt').write_bytes(b'PACKET')
            (a/'state/catalog-access.json').write_text('{"verified": true, "mode": "write"}')
            self.assertFalse(compare_initial(a,b,plan)['matches'])

    def test_changed_original_request_and_unknown_rule_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            a,b=Path(temp)/'actual',Path(temp)/'baseline'
            run_input(a,'Tue Sep 22 2026'); run_input(b,'Sun Sep 20 2026')
            with self.assertRaises(ValueError): compare_initial(a,b,{'date_revision':{'rule':'arbitrary'}})
            (a/'usage/raw/first.request.json').write_bytes(b'{}')
            with self.assertRaises(ValueError): compare_initial(a,b,{'date_revision':{'rule':RULE}})


if __name__ == '__main__': unittest.main()
