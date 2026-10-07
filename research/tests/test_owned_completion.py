"""Exercise actual local archive verification, completion receipts and adoption."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from outer.harness import preserve, util
from research import repaired_campaign as c, campaign_reassessment, acquisition_sharing


class OwnedCompletionTests(unittest.TestCase):
    def test_two_pairs_close_and_replay_without_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root/'plan.json'
            p = dict(batch=str(root), policy=c.policy())
            util.write_new_json(plan, p)
            directory = root/'waves/w'
            directory.mkdir(parents=True)
            child = dict(batch=str(root/'data'), assignments=[])
            for n in (1, 2):
                cases = [dict(condition=arm, pair=n, run_id=f'{arm}-{n}', run_instance_id=f'{arm}-{n}-uuid')
                         for arm in ('explore', 'preload')]
                child['assignments'].append(dict(pair=n, cases=cases))
                batch = root/'data'/f'pair-{n}'
                c.pair_execution.append(batch/'_control/pair-journal.jsonl', dict(kind='pair_reserved', assignments=cases))
                for case in cases:
                    source = batch/case['run_id']
                    source.mkdir(parents=True)
                    util.write_new_json(source/'manifest.json', dict(run_instance_id=case['run_instance_id'], stop_confirmed=True))
                    ref = preserve.pack(batch/'_archive', case['run_id'], {'manifest.json': source/'manifest.json'})
                    util.write_new_json(source/'archive-reference.json', ref)
                    result = source/'result.json'
                    util.write_new_json(result, dict(**case, row=dict(archive=ref)))
                    for kind in ('dispatch', 'result'):
                        c.pair_execution.append(batch/'_control/pair-journal.jsonl',
                            dict(kind=kind, **case, row=dict(archive=ref), receipt=str(result), receipt_sha256=util.sha256_file(result)))
                util.write_new_json(batch/'owned-terminal-proof.json', dict(runs=cases))
                util.write_new_json(batch/'observer-terminal.json', dict(observer_ack_verified=True))
            child_path = root/'epoch.json'
            util.write_new_json(child_path, child)
            wave = directory/'spec.json'
            w = dict(pairs=[1, 2], epoch_plan=c.live_pilot.reference(child_path))
            util.write_new_json(wave, w)
            wave_ref = c.live_pilot.reference(wave)
            plan_ref = c.live_pilot.reference(plan)
            for n in w['pairs']:
                c.pair_execution.append(root/'attempts.jsonl', dict(kind='pair_attempt_reserved', slot=n,
                    pair_attempt=1, wave=wave_ref))
            proof = directory/'verification.json'
            util.write_new_json(proof, dict(confirmed=True, plan=plan_ref, wave=wave_ref))
            util.write_new_json(directory/'_launcher/result.json', dict(kind='repaired_campaign_wave_launcher_v1_result',
                operational_complete=True, owned_closure_confirmed=True, plan=plan_ref, wave=wave_ref,
                verification=dict(confirmed=True, evidence=c.live_pilot.reference(proof))))
            util.write_new_json(directory/'result.json', dict(plan_sha256=plan_ref['sha256'],
                wave_sha256=wave_ref['sha256'], epoch_plan=w['epoch_plan'], operational_complete=True,
                errors={}, fault=None, watcher_shutdown_verified=True,
                pair_results={str(n):dict(reason='pair_publication_restore_cleanup_required') for n in w['pairs']}))
            # Only external admission, Docker listing and the already tested evaluator
            # are substituted. The closure, archive, receipt and ledger code is real.
            with patch.object(c, 'validate', return_value=p), patch.object(c, 'wave_spec', return_value=w), \
                 patch('outer.harness.runtime.docker', return_value=SimpleNamespace(stdout='')), \
                 patch.object(campaign_reassessment, 'classify', return_value=dict(classification='already_evaluable', quality=0)), \
                 patch.object(acquisition_sharing, 'validate_gate', side_effect=AssertionError('publication forbidden')):
                # Simulate a controller interruption after receipts, before closure.
                write = util.write_new_json
                def interrupted(path, value):
                    if Path(path) == directory/'closure.json':
                        raise OSError('injected interruption before adoption')
                    return write(path, value)
                with patch.object(util, 'write_new_json', side_effect=interrupted):
                    with self.assertRaisesRegex(OSError, 'injected interruption'):
                        c.close_wave(root, plan, wave)
                self.assertFalse(any(e['kind']=='pair_accepted' for e in c.ledger(p)))
                saved_receipts = {f.name:f.read_bytes() for f in directory.glob('owned-pair-*.json')}
                first = c.close_wave(root, plan, wave)
                self.assertEqual(saved_receipts, {f.name:f.read_bytes() for f in directory.glob('owned-pair-*.json')})
                receipt_bytes = {f.name:f.read_bytes() for f in directory.glob('*.json')}
                second = c.close_wave(root, plan, wave)
                self.assertEqual(first, second)
                self.assertEqual(receipt_bytes, {f.name:f.read_bytes() for f in directory.glob('*.json')})
            accepted = [e for e in c.ledger(p) if e['kind']=='pair_accepted']
            self.assertEqual([e['slot'] for e in accepted], [1, 2])
            self.assertFalse(first['publication_performed'])
            self.assertEqual(len(first['gates']), 2)


if __name__ == '__main__':
    unittest.main()
