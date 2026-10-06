"""Finite native startup protocol controls; no provider or Docker calls."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import copy
import os
import sys
import subprocess
from unittest.mock import Mock

from outer.harness import util
from research import resource_supervisor as subject


class ObserverStartup(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.phase=dict(kind=subject.RECOVERY_KIND,source_pins={'research/resource_supervisor.py':util.sha256_file(subject.__file__)})
        self.path=self.root/'phase.json'; util.write_new_json(self.path,self.phase)
        self.monitor=subject.ProcessMonitor(self.path,self.root/'observers',lambda:dict(pairs=[],assignments=[],dispatched=[]))
        self.config=dict(phase={'path':str(self.path),'sha256':util.sha256_file(self.path)},
            session=self.monitor.session,directory=str(self.monitor.directory))
        util.write_new_json(self.monitor.directory/'config.json',self.config)

    def ready(self,pid=123):
        return dict(schema_version=1,kind='resource_observer_startup_ready_v1',validated=True,
            session=self.config['session'],phase=self.config['phase'],directory=self.config['directory'],
            config_sha256=util.sha256_file(self.monitor.directory/'config.json'),observer_pid=pid,
            source_sha256=util.sha256_file(subject.__file__),ready_at=subject.now())

    def test_bound_ready_and_foreign_pid_phase_session_config_source_rejected(self):
        good=self.ready(); subject.validate_startup_ready(self.config,self.phase,123,good)
        for key,value in [('observer_pid',124),('observer_pid',True),('session','foreign'),
                ('phase',dict(path=str(self.path),sha256='f'*64)),('config_sha256','f'*64),
                ('source_sha256','f'*64),('validated',False)]:
            bad=copy.deepcopy(good); bad[key]=value
            with self.assertRaises(ValueError): subject.validate_startup_ready(self.config,self.phase,123,bad)

    def test_native_delayed_startup_precedes_enrollment_and_remains_bounded(self):
        # Eleven-second native delay discriminates against the old ten-second
        # enrollment race. This child tests only protocol timing, not validation
        # of a real acquisition plan; root separately runs the full empty probe.
        script=self.root/'delayed.py'
        script.write_text("import json,os,sys,time,hashlib\nfrom pathlib import Path\nc=json.loads(Path(sys.argv[1]).read_text())\ntime.sleep(11)\nr=json.loads(Path(sys.argv[2]).read_text());r['observer_pid']=os.getpid()\np=Path(c['directory'])/'startup-ready.json';p.write_text(json.dumps(r))\ntime.sleep(30)\n",encoding='utf-8')
        receipt=self.root/'ready-template.json'; util.write_new_json(receipt,self.ready())
        real_popen=subprocess.Popen; children=[]
        def launch(*args,**kwargs):
            child=real_popen([sys.executable,'-B',str(script),str(self.monitor.directory/'config.json'),str(receipt)],
                env=subject.safe_environment(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)); children.append(child); return child
        # start owns writing config, so remove only our own finite fixture file.
        (self.monitor.directory/'config.json').unlink()
        enrolled=[]
        try:
            with patch.object(subject.subprocess,'Popen',side_effect=launch),patch.object(self.monitor,'enroll',side_effect=lambda scope:enrolled.append(scope)):
                self.monitor.start()
            self.assertEqual(len(enrolled),1); self.assertTrue((self.monitor.directory/'startup-ready.json').exists())
        finally:
            for child in children:
                if child.poll() is None: child.terminate()
                child.wait(timeout=5)
            if hasattr(self.monitor,'log'): self.monitor.log.close()

    def test_startup_timeout_or_foreign_ready_kills_only_owned_child_before_enrollment(self):
        (self.monitor.directory/'config.json').unlink()
        child=Mock(pid=123); child.poll.return_value=None
        with patch.object(subject.subprocess,'Popen',return_value=child),\
                patch.object(self.monitor,'wait_startup',side_effect=RuntimeError('startup deadline')),\
                patch.object(self.monitor,'enroll') as enroll:
            with self.assertRaisesRegex(RuntimeError,'startup deadline'): self.monitor.start()
        enroll.assert_not_called(); child.terminate.assert_called_once(); child.wait.assert_called_once_with(timeout=10)
        self.assertEqual(self.monitor.generation,0); self.assertEqual(list(self.monitor.directory.glob('scope-*.json')),[])
        self.assertTrue(self.monitor.log.closed)

    def test_wait_failure_no_live_or_foreign_process_is_accepted(self):
        self.monitor.process=Mock(pid=123); self.monitor.process.poll.return_value=1
        with self.assertRaisesRegex(RuntimeError,'exited before'): self.monitor.wait_startup(self.config,self.phase)
        self.monitor.process.poll.return_value=None
        util.write_new_json(self.monitor.directory/'startup-ready.json',self.ready(pid=124))
        with self.assertRaises(ValueError): self.monitor.wait_startup(self.config,self.phase)
        (self.monitor.directory/'startup-ready.json').unlink()
        with patch.object(subject,'STARTUP_SECONDS',.01):
            with self.assertRaisesRegex(RuntimeError,'startup deadline'): self.monitor.wait_startup(self.config,self.phase)
        self.assertEqual((subject.CADENCE_SECONDS,subject.STALE_SECONDS,subject.STARTUP_SECONDS),(10,30,60))

    def test_supervisor_emits_ready_only_after_complete_validation_and_collector_load(self):
        class Monitor:
            def __init__(self,directory,roots,*,probe_fn=lambda _: {}): pass
        phase=dict(self.phase,batch=str(self.root/'batch'),phase_id='a'*32)
        util.write_json_atomic(self.path,phase); self.config['phase']['sha256']=util.sha256_file(self.path)
        util.write_json_atomic(self.monitor.directory/'config.json',self.config)
        with patch('research.live_pilot.validate_observer_phase',side_effect=ValueError('invalid owner')),\
                patch.object(subject,'load_monitor') as load:
            with self.assertRaisesRegex(ValueError,'invalid owner'): subject.Supervisor(self.config)
        load.assert_not_called(); self.assertFalse((self.monitor.directory/'startup-ready.json').exists())
        events=[]
        with patch('research.live_pilot.validate_observer_phase',side_effect=lambda *a:events.append('full validation')),\
                patch.object(subject,'load_monitor',side_effect=lambda *a:(events.append('collector loaded') or Monitor)):
            observer=subject.Supervisor(self.config)
        self.addCleanup(observer.pool.shutdown)
        self.assertEqual(events,['full validation','collector loaded'])
        ready=util.read_json(self.monitor.directory/'startup-ready.json')
        subject.validate_startup_ready(self.config,phase,os.getpid(),ready)

    def test_partial_publication_waits_but_complete_foreign_receipt_rejects(self):
        self.monitor.process=Mock(pid=123); self.monitor.process.poll.return_value=None
        path=self.monitor.directory/'startup-ready.json'; path.write_text('{',encoding='utf-8')
        import threading,time
        def complete():
            time.sleep(.1); util.write_json_atomic(path,self.ready())
        writer=threading.Thread(target=complete); writer.start()
        try: self.monitor.wait_startup(self.config,self.phase)
        finally: writer.join(timeout=2)
        self.assertFalse(writer.is_alive())
        util.write_json_atomic(path,self.ready(pid=124))
        with self.assertRaises(ValueError): self.monitor.wait_startup(self.config,self.phase)

    def test_scope_provider_exception_also_bounds_unenrolled_owned_child(self):
        (self.monitor.directory/'config.json').unlink()
        self.monitor.scope_provider=Mock(side_effect=RuntimeError('scope unavailable'))
        child=Mock(pid=123); child.poll.return_value=None
        with patch.object(subject.subprocess,'Popen',return_value=child),patch.object(self.monitor,'wait_startup'):
            with self.assertRaisesRegex(RuntimeError,'scope unavailable'): self.monitor.start()
        child.terminate.assert_called_once(); child.wait.assert_called_once_with(timeout=10)
        self.assertTrue(self.monitor.log.closed)


if __name__=='__main__': unittest.main()
