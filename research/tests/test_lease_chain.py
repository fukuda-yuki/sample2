"""Finite actual saved-chain fixtures; no provider, key, or original mutations."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import copy,json,subprocess,sys,tempfile,unittest
from unittest.mock import patch
from outer.harness import util
from research import pair_execution as pair,wave_campaign as campaign,wave_dispatch,wave_plan,wave_sharing

CANONICAL=Path(__file__).resolve().parents[2].parent/'v5-go30m'
PHASE8=CANONICAL/'artifacts/main-central-wave-v8-fixed-20261005/phase.json'
BOUNDARY=CANONICAL/'artifacts/v8-lease-start-recovery-20261005/actual-empty-v8-boundary.json'


class LeaseTests(unittest.TestCase):
    def setUp(self):
        if not PHASE8.is_file() or not BOUNDARY.is_file():
            self.skipTest('Private saved V8 acquisition boundary is required for these finite acceptance fixtures')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.control=Path(self.tmp.name);self.p8=util.read_json(PHASE8)
        original_control=Path(self.p8['batch'])/'_control'
        util.write_new_json(self.control/'phase-handoff.json',util.read_json(original_control/'phase-handoff.json'))
        parent=self.control/'phase-handoff.json'
        for version in range(2,9):
            value=util.read_json(original_control/f'phase-handoff-v{version}.json')
            value['previous_handoff']={'path':str(parent),'sha256':util.sha256_file(parent)}
            current=self.control/f'phase-handoff-v{version}.json';util.write_new_json(current,value);parent=current
        self.owner8=util.sha256_file(PHASE8)

    def acquire(self,permit):
        with pair.exclusive(self.control,phase_permit=permit):pass

    def add9(self):
        p9={**self.p8,'kind':wave_plan.V9_KIND,'schema_version':9,
            'predecessor_phase':{'path':str(PHASE8),'sha256':self.owner8},
            'predecessor_journal':{'path':str(Path(self.p8['batch'])/'_control'/self.p8['phase_id']/'wave-journal.jsonl'),'sha256':None,'absent':True},
            'predecessor_gates':{}}
        pp=self.control/'fixture-phase9.json';util.write_new_json(pp,p9)
        parent=self.control/'phase-handoff-v8.json'
        marker={'kind':'central_fixed_wave_successor_handoff_v9','previous_handoff':{'path':str(parent),'sha256':util.sha256_file(parent)},
            'previous_phase_sha256':self.owner8,'new_phase':{'path':str(pp),'sha256':util.sha256_file(pp)},
            'predecessor_journal':p9['predecessor_journal'],'predecessor_gates':{}}
        util.write_new_json(self.control/'phase-handoff-v9.json',marker)
        return util.sha256_file(pp)

    def test_actual_saved_v8_chain_accepts_only8(self):
        before={p.name:util.sha256_file(p) for p in self.control.glob('*.json')}
        self.acquire(self.owner8)
        for permit in (None,self.p8['predecessor_phase']['sha256'],'foreign'):
            with self.assertRaises(ValueError):self.acquire(permit)
        self.assertEqual(before,{p.name:util.sha256_file(p) for p in self.control.glob('*.json')})

    def test_v9_only_after_handoff_and_old_markers_unchanged(self):
        before={p.name:util.sha256_file(p) for p in self.control.glob('*.json')}
        owner9=self.add9();self.acquire(owner9)
        with self.assertRaises(ValueError):self.acquire(self.owner8)
        self.assertEqual(before,{n:util.sha256_file(self.control/n) for n in before})

    def test_missing_intermediate_rejected(self):
        (self.control/'phase-handoff-v4.json').unlink()
        with self.assertRaisesRegex(ValueError,'intermediate'):self.acquire(self.owner8)

    def test_changed_hash_path_kind_rejected(self):
        target=self.control/'phase-handoff-v8.json';baseline=util.read_json(target)
        for change in ('hash','path','kind'):
            with self.subTest(change=change):
                value=copy.deepcopy(baseline)
                if change=='hash':value['previous_handoff']['sha256']='0'*64
                if change=='path':value['previous_handoff']['path']=str(self.control/'foreign.json')
                if change=='kind':value['kind']='legacy_accepted'
                util.write_json_atomic(target,value)
                with self.assertRaises(ValueError):self.acquire(self.owner8)

    def test_unsupported_successor_rejected(self):
        for name in ('phase-handoff-v11.json','phase-handoff-vbogus.json'):
            target=self.control/name;util.write_new_json(target,{})
            with self.assertRaisesRegex(ValueError,'Unsupported'):self.acquire(self.owner8)
            target.unlink()

    def test_competing_process_rejected_then_release_reacquired(self):
        owner9=self.add9()
        script='from pathlib import Path;from research.pair_execution import exclusive;import sys\ntry:\n with exclusive(Path(sys.argv[1]),phase_permit=sys.argv[2]):pass\nexcept OSError:sys.exit(7)\n'
        args=[sys.executable,'-B','-X','utf8','-c',script,str(self.control),owner9]
        with pair.exclusive(self.control,phase_permit=owner9):
            result=subprocess.run(args,capture_output=True,cwd=Path(__file__).resolve().parents[2],timeout=15)
            self.assertEqual(result.returncode,7)
        result=subprocess.run(args,capture_output=True,cwd=Path(__file__).resolve().parents[2],timeout=15)
        self.assertEqual(result.returncode,0)

    def test_v9_absence_guard_rejects_existing_even_empty_journal(self):
        expected=Path(self.p8['batch'])/'_control'/self.p8['phase_id']/'wave-journal.jsonl'
        proposal={'kind':wave_plan.V9_KIND,'predecessor_phase':{'path':str(PHASE8),'sha256':self.owner8},
            'predecessor_journal':{'path':str(expected),'sha256':None,'absent':True},'predecessor_gates':{},
            'predecessor_empty_boundary':{'path':str(BOUNDARY),'sha256':util.sha256_file(BOUNDARY)}}
        old_exists=Path.exists
        def journal_exists(p):return True if p==expected else old_exists(p)
        with patch.object(wave_plan,'validate_v8',return_value={}):
            with patch.object(Path,'exists',journal_exists):
                with self.assertRaisesRegex(ValueError,'even a new empty file'):wave_plan._v9_empty_predecessor(proposal)
            bad={**proposal,'predecessor_journal':{'path':str(expected),'sha256':'0'*64}}
            with self.assertRaises(ValueError):wave_plan._v9_empty_predecessor(bad)

    def test_v9_publication_uses_real_v3_ancestor_and_discloses_absence(self):
        phase={**self.p8,'kind':wave_plan.V9_KIND,'schema_version':9,'phase_id':'central-wave-pair58-100-v9',
            'predecessor_phase':{'path':str(PHASE8),'sha256':self.owner8},
            'predecessor_journal':{'path':'absent-8-journal','sha256':None,'absent':True},
            'predecessor_empty_boundary':{'path':str(BOUNDARY),'sha256':util.sha256_file(BOUNDARY)}}
        d=SimpleNamespace(repo=CANONICAL,phase=phase,digest='fixture9',current=lambda:{'waves':[{'pairs':[58,59],'run_cap':4}]})
        metadata=wave_sharing.Publisher(d).metadata(58)
        self.assertTrue(metadata['predecessor_journal_absent'])
        self.assertIsNone(metadata['predecessor_journal_sha256'])
        self.assertEqual(metadata['predecessor_empty_boundary_sha256'],util.sha256_file(BOUNDARY))
        ancestor=phase
        while ancestor['kind']!=wave_plan.V3_KIND:ancestor=util.read_json(ancestor['predecessor_phase']['path'])
        self.assertEqual(metadata['cause_condition_acceptance_sha256'],ancestor['resource_collector_acceptance']['sha256'])

    def test_v9_campaign_chooses_independent_process_and_own_warmup(self):
        phase={**self.p8,'kind':wave_plan.V9_KIND,'schema_version':9}
        pp=self.control/'campaign9.json';util.write_new_json(pp,phase)
        approval={'approved_by':'user','authorized':True,'phase_sha256':util.sha256_file(pp),
                  'authorization_reference':{'path':str(PHASE8),'sha256':self.owner8}}
        ap=self.control/'approval.json';util.write_new_json(ap,approval)
        @contextmanager
        def session():yield
        d=SimpleNamespace(phase_control=self.control,resource_scope=lambda:{'pairs':[],'assignments':[],'dispatched':set()},session=session)
        adapters=SimpleNamespace(**{name:lambda *a:None for name in ('prepare','verify','implement','postprocess','reconcile','fence')})
        monitor=SimpleNamespace(start=lambda:None,stop=lambda:True)
        with patch.object(campaign,'preflight'),patch.object(wave_dispatch,'handoff_v9') as handoff,\
             patch.object(campaign.wave_execution,'HarnessAdapters',return_value=adapters),\
             patch.object(wave_dispatch,'Dispatcher',return_value=d),\
             patch.object(wave_sharing,'Publisher'),patch.object(campaign,'Health'),\
             patch.object(campaign,'load_monitor',side_effect=AssertionError('legacy monitor chosen')),\
             patch('research.resource_supervisor.ProcessMonitor',return_value=monitor) as independent,\
             patch.object(campaign,'warmup',return_value=True) as warmup,\
             patch.object(campaign,'drive',return_value={'status':'complete'}):
            self.assertEqual(campaign.run_campaign(CANONICAL,pp,ap)['status'],'complete')
            handoff.assert_called_once();independent.assert_called_once();warmup.assert_called_once()


if __name__=='__main__':unittest.main()
