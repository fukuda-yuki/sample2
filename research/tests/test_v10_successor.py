"""Bounded lease/routing checks. Isolated markers, no formal Run mutation."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import copy, unittest
from unittest.mock import patch
from outer.harness import util
from research import pair_execution as pair, wave_campaign as campaign, wave_dispatch, wave_plan, wave_sharing
from research.tests import test_lease_chain as lease_fixtures
CANONICAL = lease_fixtures.CANONICAL


class V10Tests(unittest.TestCase):
    setUp = lease_fixtures.LeaseTests.setUp
    acquire = lease_fixtures.LeaseTests.acquire
    add9 = lease_fixtures.LeaseTests.add9

    def add10(self):
        owner9 = self.add9()
        previous = self.control/'fixture-phase9.json'
        phase = {**util.read_json(previous), 'kind':wave_plan.V10_KIND, 'schema_version':10,
            'predecessor_phase':{'path':str(previous),'sha256':owner9}}
        path=self.control/'fixture-phase10.json';util.write_new_json(path,phase)
        parent=self.control/'phase-handoff-v9.json'
        util.write_new_json(self.control/'phase-handoff-v10.json',{
            'kind':'central_fixed_wave_successor_handoff_v10',
            'previous_handoff':{'path':str(parent),'sha256':util.sha256_file(parent)},
            'previous_phase_sha256':owner9,'new_phase':{'path':str(path),'sha256':util.sha256_file(path)},
            'predecessor_journal':phase['predecessor_journal'],'predecessor_gates':{}})
        return owner9,util.sha256_file(path)

    def test_v10_only_owner_after_exact_handoff(self):
        before={p.name:util.sha256_file(p) for p in self.control.glob('*.json')}
        owner9,owner10=self.add10();self.acquire(owner10)
        for old in (None,self.owner8,owner9,'foreign'):
            with self.assertRaises(ValueError):self.acquire(old)
        self.assertEqual(before,{n:util.sha256_file(self.control/n) for n in before})
        self.acquire(owner10)

    def test_v10_missing_intermediate_or_changed_binding_rejected(self):
        _,owner10=self.add10();target=self.control/'phase-handoff-v10.json'
        baseline=util.read_json(target)
        for field in ('previous_phase_sha256','kind'):
            value=copy.deepcopy(baseline);value[field]='invalid';util.write_json_atomic(target,value)
            with self.assertRaises(ValueError):self.acquire(owner10)
        util.write_json_atomic(target,baseline)
        (self.control/'phase-handoff-v9.json').unlink()
        with self.assertRaises(ValueError):self.acquire(owner10)

    def test_v10_campaign_uses_independent_monitor(self):
        phase={**self.p8,'kind':wave_plan.V10_KIND,'schema_version':10}
        pp=self.control/'campaign10.json';util.write_new_json(pp,phase)
        approval={'approved_by':'user','authorized':True,'phase_sha256':util.sha256_file(pp),
            'authorization_reference':{'path':str(self.control/'phase-handoff.json'),'sha256':util.sha256_file(self.control/'phase-handoff.json')}}
        ap=self.control/'approval10.json';util.write_new_json(ap,approval)
        @contextmanager
        def session():yield
        d=SimpleNamespace(phase_control=self.control,resource_scope=lambda:{'pairs':[],'assignments':[],'dispatched':set()},session=session)
        adapters=SimpleNamespace(**{name:lambda *a:None for name in ('prepare','verify','implement','postprocess','reconcile','fence')})
        monitor=SimpleNamespace(start=lambda:None,stop=lambda:True)
        with patch.object(campaign,'preflight'),patch.object(wave_dispatch,'handoff_v10') as handoff,\
             patch.object(campaign.wave_execution,'HarnessAdapters',return_value=adapters),\
             patch.object(wave_dispatch,'Dispatcher',return_value=d),patch.object(wave_sharing,'Publisher'),\
             patch.object(campaign,'Health'),patch.object(campaign,'load_monitor',side_effect=AssertionError('legacy monitor chosen')),\
             patch('research.resource_supervisor.ProcessMonitor',return_value=monitor) as independent,\
             patch.object(campaign,'warmup',return_value=True) as warmup,\
             patch.object(campaign,'drive',return_value={'status':'complete'}):
            self.assertEqual(campaign.run_campaign(CANONICAL,pp,ap)['status'],'complete')
            handoff.assert_called_once();independent.assert_called_once();warmup.assert_called_once()

    def test_v10_publication_retains_real_v9_journal(self):
        pp=CANONICAL/'artifacts/main-central-wave-v9-fixed-20261005/phase.json'
        p9=util.read_json(pp);journal=Path(p9['batch'])/'_control'/p9['phase_id']/'wave-journal.jsonl'
        phase={**p9,'kind':wave_plan.V10_KIND,'schema_version':10,'phase_id':'central-wave-pair68-100-v10',
            'predecessor_phase':{'path':str(pp),'sha256':util.sha256_file(pp)},
            'predecessor_journal':{'path':str(journal),'sha256':util.sha256_file(journal)},
            'completed_pairs':list(range(1,68))}
        d=SimpleNamespace(repo=CANONICAL,phase=phase,digest='isolated-routing-only',
            current=lambda:{'waves':[{'pairs':[68,69],'run_cap':4}]})
        metadata=wave_sharing.Publisher(d).metadata(68)
        self.assertEqual(metadata['predecessor_journal_sha256'],util.sha256_file(journal))
        self.assertNotIn('predecessor_journal_absent',metadata)
        self.assertEqual(metadata['completed_earlier_pairs'],list(range(1,68)))


if __name__=='__main__':unittest.main()
