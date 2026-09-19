import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import support
from harness import runtime, util, cli, machine


class NetworkCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'run'; self.root.mkdir()
        self.name = 's2-net-' + 'a'*16
        self.state = {'run_id':'run', 'run_instance_id':'instance', 'network':self.name,
            'network_id':'network-id', 'worker':'worker', 'gateway':'gateway', 'stop_confirmed':True}
        util.write_new_json(self.root/'runtime.json', self.state)
        self.manifest = {'run_id':'run', 'run_instance_id':'instance', 'stop_confirmed':True,
            'ended_at':'original-time', 'end_reason':'completed', 'duration_seconds':3}
        util.write_new_json(self.root/'manifest.json', self.manifest)
        self.network = {'Name':self.name, 'Id':'network-id', 'Labels':{'sample2.run':'run','sample2.instance':'instance'},
            'Internal':True, 'Driver':'bridge', 'Containers':{}}
        self.present, self.fail_remove, self.fail_list = True, False, False
        self.containers, self.removed = [], []

    def docker(self, *args, **kwargs):
        if args[:2] == ('network','ls'):
            if self.fail_list: raise RuntimeError('daemon unavailable')
            value = json.dumps({'Name':self.name,'ID':'network-id'}) if self.present else ''
        elif args[:2] == ('network','inspect'): value = json.dumps([self.network])
        elif args[:2] == ('network','rm'):
            if self.fail_remove: raise RuntimeError('injected removal failure')
            self.removed.append(args[2]); self.present = False; value = args[2]
        elif args[:2] == ('ps','-aq'): value = 'container' if self.containers else ''
        elif args[0] == 'inspect': value = '\n'.join(json.dumps(c) for c in self.containers)
        else: raise AssertionError(args)
        return SimpleNamespace(returncode=0, stdout=value, stderr='')

    def test_exact_network_removed_and_repeat_is_idempotent(self):
        before = (self.root/'manifest.json').read_bytes()
        with patch.object(runtime, 'docker', side_effect=self.docker):
            a = runtime.cleanup_network(self.root, evidence_dir=Path(self.tmp.name)/'external')
            b = runtime.cleanup_network(self.root, evidence_dir=Path(self.tmp.name)/'external')
        self.assertEqual((a['status'], b['status']), ('removed','absent'))
        self.assertEqual(self.removed, ['network-id'])
        self.assertEqual(before, (self.root/'manifest.json').read_bytes())

    def test_absence_requires_healthy_docker_listing(self):
        self.present = False; self.fail_list = True
        with patch.object(runtime, 'docker', side_effect=self.docker): r = runtime.cleanup_network(self.root)
        self.assertFalse(r['confirmed']); self.assertEqual(self.removed, [])

    def test_foreign_network_or_active_endpoint_is_never_removed(self):
        for field, value in [('Id','replaced-id'), ('Internal',False), ('Containers',{'foreign':{}}),
                             ('Labels',{'sample2.run':'run','sample2.instance':'other-instance'})]:
            with self.subTest(field=field):
                old = self.network[field]; self.network[field] = value
                with patch.object(runtime, 'docker', side_effect=self.docker): r = runtime.cleanup_network(self.root)
                self.assertFalse(r['confirmed']); self.assertEqual(self.removed, [])
                self.network[field] = old

    def test_foreign_container_reference_is_rejected_even_when_stopped(self):
        self.containers = [{'id':'c','name':'/foreign','state':{'Running':False},'labels':{},'networks':{self.name:{}}}]
        with patch.object(runtime, 'docker', side_effect=self.docker): r = runtime.cleanup_network(self.root)
        self.assertFalse(r['confirmed']); self.assertEqual(self.removed, [])

    def test_owned_container_must_be_stopped_and_instance_bound(self):
        for live, instance in [(True,'instance'),(False,'other')]:
            with self.subTest(live=live,instance=instance):
                self.containers = [{'id':'c','name':'/worker','state':{'Running':live},
                    'labels':{'sample2.run':'run','sample2.instance':instance},'networks':{self.name:{}}}]
                with patch.object(runtime, 'docker', side_effect=self.docker): r = runtime.cleanup_network(self.root)
                self.assertFalse(r['confirmed']); self.assertEqual(self.removed, [])

    def test_stop_retries_cleanup_without_restarting_or_changing_measured_interval(self):
        self.fail_remove = True
        with patch.object(runtime, 'docker', side_effect=self.docker), patch.object(runtime, 'start') as start:
            a = runtime.request_stop(self.root)
            self.fail_remove = False
            b = runtime.request_stop(self.root)
        self.assertTrue(a['stop_confirmed']); self.assertFalse(a['network_cleanup']['confirmed'])
        self.assertTrue(b['network_cleanup']['confirmed']); start.assert_not_called()
        after = util.read_json(self.root/'manifest.json')
        for k,v in self.manifest.items(): self.assertEqual(after[k], v)

    def test_cli_run_returns_failure_for_cleanup_failure_with_saved_result(self):
        row = {'execution':{'state':'completed'},'scoring':{'state':'scored'},'usage':{'usage_complete':True},
            'network_cleanup':{'confirmed':False},'archive':{'package_id':'retained'}}
        with patch.object(machine,'execute',return_value=row), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(['run','--task','MS1-001','--intervention','explore'])
        self.assertEqual(code,1)
