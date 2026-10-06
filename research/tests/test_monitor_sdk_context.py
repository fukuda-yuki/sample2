"""Monitor command context and saved readback; no real SDK/monitor execution."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from outer.harness import monitor, util


class MonitorSdkContextTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base/'controller'; self.repo.mkdir()
        self.monitor_root = self.base/'monitor'; self.monitor_root.mkdir()
        util.write_new_json(self.repo/'global.json', {'sdk':{'version':'8.0.425'}})
        util.write_new_json(self.monitor_root/'global.json', {'sdk':{'version':'10.0.100'}})
        project = self.monitor_root/'src/CopilotAgentObservability.ConfigCli/CopilotAgentObservability.ConfigCli.csproj'
        project.parent.mkdir(parents=True); project.write_text('<Project/>')
        self.root = self.base/'saved-run'; self.root.mkdir()
        self.event = dict(request_id='finite-request', model_id='deepseek-v4.1-flash',status='completed',
            started_at='2026-10-06T00:00:00+00:00',usage=dict(input_tokens=82,output_tokens=58))
        util.append_line(self.root/'usage/events.jsonl',self.event)
        util.write_new_json(self.root/'usage/normalized.json',dict(usage_complete=True))
        util.write_new_json(self.root/'manifest.json',dict(run_instance_id='1'*32,task_id='MS1-CONT-A'))
        self.calls = []
        self.wrong_readback = False

    def command(self, args, **kwargs):
        self.calls.append((args,kwargs))
        if args[0] == 'git': return SimpleNamespace(stdout='c'*40,stderr='')
        self.assertEqual(kwargs.get('cwd'),self.monitor_root,
            'dotnet must resolve global.json from monitor checkout, regardless of launcher cwd')
        self.assertEqual(kwargs.get('timeout'),300)
        if 'ingest-raw' in args:
            raw=Path(args[args.index('ingest-raw')+1]); database=Path(args[args.index('--db')+1])
            with closing(sqlite3.connect(database)) as db:
                db.execute('CREATE TABLE raw_records (id INTEGER,payload_json TEXT)')
                db.execute('INSERT INTO raw_records VALUES (1,?)',(json.dumps(util.read_json(raw)),))
                db.commit()
        elif 'normalize-raw' in args:
            util.write_json_atomic(Path(args[args.index('--json')+1]),[dict(experiment_id=self.root.name,
                turn_count=1,input_tokens=999 if self.wrong_readback else 82,output_tokens=58)])
        else: self.fail('Unexpected monitor invocation')
        return SimpleNamespace(stdout='finite monitor leaf',stderr='')

    def link(self):
        with patch.dict('os.environ', {'SAMPLE2_MONITOR_ROOT':str(self.monitor_root)}), \
                patch.object(monitor.runtime,'command',side_effect=self.command):
            return monitor.link(self.repo,self.root)

    def test_ingest_and_normalize_use_monitor_sdk_context_not_controller_sdk(self):
        receipt=self.link()
        self.assertTrue(receipt['verified'])
        dotnet=[(args,kw) for args,kw in self.calls if args[0]=='dotnet']
        self.assertEqual(len(dotnet),2)
        self.assertTrue(all(kw['cwd']==self.monitor_root for _,kw in dotnet))
        self.assertEqual(receipt['monitor_commit'],'c'*40)
        self.assertEqual(receipt['usage_totals']['input_tokens']['total'],82)

    def test_existing_database_is_never_reingested_normalization_keeps_monitor_context(self):
        self.link()
        original=util.sha256_file(self.root/'telemetry/gateway.otlp.json')
        self.link()
        self.assertEqual(sum('ingest-raw' in args for args,_ in self.calls),1)
        self.assertEqual(sum('normalize-raw' in args for args,_ in self.calls),2)
        self.assertEqual(util.sha256_file(self.root/'telemetry/gateway.otlp.json'),original)
        with closing(sqlite3.connect((self.root/'telemetry/monitor.db').as_uri()+'?mode=ro',uri=True)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM raw_records').fetchone()[0],1)

    def test_relative_monitor_setting_resolved_before_changing_child_cwd(self):
        with patch.dict('os.environ',{'SAMPLE2_MONITOR_ROOT':'monitor'}), \
                patch('os.getcwd',return_value=str(self.base)), \
                patch.object(monitor.runtime,'command',side_effect=self.command):
            receipt=monitor.link(self.repo,self.root)
        self.assertTrue(receipt['verified'])

    def test_incomplete_usage_keeps_observed_readback_without_inventing_total(self):
        util.write_json_atomic(self.root/'usage/normalized.json',dict(usage_complete=False))
        receipt=self.link()
        self.assertTrue(receipt['verified'])
        self.assertFalse(receipt['usage_complete'])
        self.assertEqual(receipt['usage_totals']['input_tokens']['observed'],82)
        self.assertIsNone(receipt['usage_totals']['input_tokens']['total'])

    def test_wrong_readback_remains_failure_with_durable_unverified_receipt(self):
        self.wrong_readback=True
        with self.assertRaises(RuntimeError): self.link()
        receipt=util.read_json(self.root/'telemetry-link.json')
        self.assertFalse(receipt['verified'])
        self.assertFalse(receipt['readback']['input_tokens']['matched'])

    def test_changed_source_events_refuse_before_second_import_or_normalization(self):
        self.link(); original=util.sha256_file(self.root/'telemetry/gateway.otlp.json')
        util.append_line(self.root/'usage/events.jsonl',dict(self.event,request_id='second-request'))
        before=len(self.calls)
        with self.assertRaises(ValueError): self.link()
        self.assertEqual(len(self.calls),before)
        self.assertEqual(util.sha256_file(self.root/'telemetry/gateway.otlp.json'),original)
