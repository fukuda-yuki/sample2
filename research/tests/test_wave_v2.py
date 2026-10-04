"""Finite successor handoff and future-only dispatch; no real resource/model I/O."""
from pathlib import Path
import json
import unittest
from unittest.mock import patch

from outer.harness import util
from research import pair_execution, wave_plan, wave_dispatch, wave_campaign, wave_sharing
from research.tests import test_wave_dispatch as fixtures


class V2Tests(unittest.TestCase):
    verify = fixtures.WaveTests.verify
    postprocess = fixtures.WaveTests.postprocess
    publish = fixtures.WaveTests.publish
    dispatcher = fixtures.WaveTests.dispatcher

    def prepare(self, binding):
        manifest = fixtures.WaveTests.prepare(self, binding)
        root = self.batch / binding['run_id']
        (root / 'usage/raw').mkdir(parents=True); (root / 'usage/raw/fixed').write_bytes(b'fixed raw')
        util.write_new_json(root / 'snapshot.json', {'fixed': binding['run_instance_id']})
        return manifest

    def implement(self, repo, batch, rid):
        receipt = fixtures.WaveTests.implement(self, repo, batch, rid)
        root = batch / rid; manifest = util.read_json(root / 'manifest.json')
        manifest.update(stop_confirmed=True, submission_fixed=True); util.write_json_atomic(root / 'manifest.json', manifest)
        return {**receipt, 'raw': util.tree_hashes(root / 'usage/raw'), 'snapshot_sha256': util.sha256_file(root / 'snapshot.json')}

    def setUp(self):
        fixtures.WaveTests.setUp(self)
        for p in self.original['assignments'][:5]:
            for c in p['cases']:
                self.prepare(c); root = self.batch / c['run_id']
                manifest = util.read_json(root / 'manifest.json'); manifest.update(stop_confirmed=True, submission_fixed=True)
                util.write_json_atomic(root / 'manifest.json', manifest)
                self.old['implementations'][c['run_id']]['receipt'].update(submission_fixed=True,
                    raw=util.tree_hashes(root / 'usage/raw'), snapshot_sha256=util.sha256_file(root / 'snapshot.json'))
        olddir = self.repo / 'old-collector'; olddir.mkdir()
        oldmonitor = olddir / 'wave_resource_monitor.py'; oldmonitor.write_bytes(b'unchanged monitor')
        oldprobe = olddir / 'wave_resource_probe.py'; oldprobe.write_bytes(b'old probe')
        oldaccept = olddir / 'acceptance.json'; util.write_new_json(oldaccept, {'old': True})
        ref = lambda p: {'path': str(p), 'sha256': util.sha256_file(p)}
        self.phase.update(resource_monitor=ref(oldmonitor), resource_probe=ref(oldprobe), resource_collector_acceptance=ref(oldaccept))
        util.write_json_atomic(self.path, self.phase); self.digest = util.sha256_file(self.path); self.approval['phase_sha256'] = self.digest
        previous = self.dispatcher()
        with previous.session():
            previous.execute_next(); previous.execute_next(escalate=True)
        self.previous_path, self.previous_digest = self.path, self.digest
        self.previous_phase = self.phase
        self.previous_journal = previous.journal
        self.previous_marker = (previous.control / 'phase-handoff.json').read_bytes()
        newdir = self.repo / 'new-collector'; newdir.mkdir()
        monitor = newdir / 'wave_resource_monitor.py'; monitor.write_bytes(oldmonitor.read_bytes())
        probe = newdir / 'wave_resource_probe.py'; probe.write_bytes(b'fixed probe fixture')
        acceptance = newdir / 'acceptance.json'; util.write_new_json(acceptance, {
            'kind': 'resource_probe_only_v2_nonlive_acceptance', 'previous_probe_sha256': ref(oldprobe)['sha256'],
            'resource_probe_sha256': ref(probe)['sha256'], 'resource_monitor_sha256': ref(monitor)['sha256'],
            'operational_policy_sha256': self.phase['operational_policy']['sha256'],
            'fail_closed_unchanged': True, 'model_called': False, 'run_created': False})
        self.phase = wave_plan.build_v2(self.previous_path, previous.journal, source_commit='new fixture source',
            source_pins=self.phase['source_pins'], resource_monitor=ref(monitor), resource_probe=ref(probe),
            resource_collector_acceptance=ref(acceptance))
        self.path = self.repo / 'phase-v2.json'; util.write_new_json(self.path, self.phase)
        self.digest = util.sha256_file(self.path); self.approval = {**self.approval, 'phase_sha256': self.digest}
        self.sent.clear(); self.heavy.clear(); self.peak = 0

    def handoff(self):
        return wave_dispatch.handoff_v2(self.repo, self.path, self.approval)

    def test_exact_future_assignments_and_historical_v1_readability(self):
        self.assertEqual(self.phase['assignments'], self.original['assignments'][11:])
        self.assertEqual(len({c['run_instance_id'] for p in self.phase['assignments'] for c in p['cases']}), 178)
        wave_plan.validate(self.previous_phase)
        historical = wave_dispatch.state(self.previous_journal, self.previous_phase, self.previous_digest)
        self.assertEqual(set(historical['gates']), set(range(6, 12)))
        self.assertEqual(self.phase['responsibility_counts'], [21, 22, 24, 22])

    def test_handoff_preserves_marker_and_fences_legacy_and_active_owner(self):
        control = self.batch / '_control'
        with pair_execution.exclusive(control, phase_permit=self.previous_digest):
            with self.assertRaises(OSError): self.handoff()
            with self.assertRaises(OSError):
                wave_plan.build_v2(self.previous_path, self.previous_journal, source_commit=self.phase['source_commit'],
                    source_pins=self.phase['source_pins'], resource_monitor=self.phase['resource_monitor'],
                    resource_probe=self.phase['resource_probe'], resource_collector_acceptance=self.phase['resource_collector_acceptance'])
        self.assertEqual(self.handoff()['status'], 'handed_off')
        self.assertEqual((control / 'phase-handoff.json').read_bytes(), self.previous_marker)
        with self.assertRaises(ValueError):
            with pair_execution.exclusive(control, phase_permit=self.previous_digest): pass
        self.assertEqual(self.handoff()['status'], 'handed_off')
        base = control / 'phase-handoff.json'; base.unlink()
        for permit in (None, self.previous_digest, self.digest):
            with self.assertRaisesRegex(ValueError, 'Missing immutable predecessor'):
                with pair_execution.exclusive(control, phase_permit=permit): pass
        base.write_bytes(self.previous_marker)
        modified = {**self.approval, 'authorization_reference': 'different authorization'}
        with self.assertRaisesRegex(ValueError, 'cannot be overwritten'): wave_dispatch.handoff_v2(self.repo, self.path, modified)

    def test_missing_gate_or_changed_journal_phase_raw_and_snapshot_rejected(self):
        gate = Path(self.phase['predecessor_gates']['11']['path'])
        raw = self.batch / self.previous_phase['assignments'][0]['cases'][0]['run_id'] / 'usage/raw/fixed'
        snapshot = raw.parents[2] / 'snapshot.json'
        missing = {**self.phase, 'predecessor_gates': {k: v for k, v in self.phase['predecessor_gates'].items() if k != '11'}}
        with self.assertRaises(ValueError): wave_plan.validate(missing)
        old = gate.read_bytes(); gate.unlink()
        with self.assertRaises((ValueError, OSError)): wave_plan.validate(self.phase)
        gate.write_bytes(old)
        for path in (gate, self.previous_journal, self.previous_path, raw, snapshot):
            with self.subTest(path=path):
                old = path.read_bytes(); path.write_bytes(old + b'changed')
                with self.assertRaises((ValueError, OSError)): wave_plan.validate(self.phase)
                path.write_bytes(old)

    def test_duplicate_old_identity_and_policy_or_monitor_change_rejected(self):
        bad = {**self.phase, 'assignments': [self.previous_phase['assignments'][0], *self.phase['assignments'][1:]]}
        with self.assertRaises(ValueError): wave_plan.validate(bad)
        with self.assertRaises(ValueError): wave_plan.validate({**self.phase, 'maximum_pairs': 4})
        with self.assertRaises(ValueError): wave_plan.validate({**self.phase, 'thresholds': {**self.phase['thresholds'], 'cpu_percent_max': 99}})
        ref = self.phase['resource_monitor']; Path(ref['path']).write_bytes(b'changed monitor')
        with self.assertRaises(ValueError): wave_plan.validate({**self.phase, 'resource_monitor': {**ref, 'sha256': util.sha256_file(ref['path'])}})

    def test_dirty_source_is_rejected_before_any_runtime_or_model_access(self):
        for name in ('research/wave_campaign.py', 'research/wave_sharing.py'):
            path = self.repo / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'fixture code')
            self.phase['source_pins'][name] = util.sha256_file(path)
        with patch.object(wave_campaign.wave_execution, 'preflight', return_value={}), patch.object(
                wave_campaign.next_phase, 'git', side_effect=[self.phase['source_commit'], ' M changed.py']):
            with self.assertRaisesRegex(ValueError, 'not clean'): wave_campaign.preflight(self.repo, self.phase)

    def test_conservative_four_run_wave_rejects_eight_run_journal(self):
        self.handoff(); d = self.dispatcher()
        with d.session():
            self.assertEqual(d.execute_next(escalate=True)['pairs'], [12, 13])
            self.assertEqual(d.execute_next(escalate=True)['pairs'], [14, 15])
            self.assertEqual(self.peak, 4)
            d.record('wave_reserved', pairs=[16, 17, 18, 19], blocks=2, run_cap=8, assignments=[])
            with self.assertRaises(ValueError): d.current()

    def test_no_refill_public_metadata_and_hashes_stay_bound(self):
        self.handoff(); d = self.dispatcher(publication_ready=lambda number, current: False)
        with d.session():
            self.assertEqual(d.execute_next()['reason'], 'publication_review_pending')
            self.assertEqual(d.execute_next()['reason'], 'previous_wave_gates_or_explicit_recovery')
            metadata = wave_sharing.Publisher(d).metadata(12)
            self.assertEqual(metadata['predecessor_phase_sha256'], self.previous_digest)
            self.assertEqual(metadata['maximum_pairs'], 2)
            self.assertIn('pairs1–11', metadata['limitation'])
            self.assertEqual(len(self.sent), 4)

    def test_all89_future_pairs178_unique_sends_gates_never_eight(self):
        self.handoff(); d = self.dispatcher()
        with d.session():
            result = d.execute_next(escalate=True)
            while result['status'] != 'complete': result = d.execute_next(escalate=True)
            current = d.current()
            self.assertEqual(set(current['gates']), set(range(12, 101)))
            self.assertEqual(len(current['dispatch']), 178)
            self.assertEqual(len(set(self.sent)), 178)
            self.assertEqual(self.peak, 4)
            self.assertEqual(current['waves'][-1]['pairs'], [100])
            self.assertEqual(result['phase_pairs'], 89)
            tail = d.journal.read_bytes()
            # A forged final one-pair block cannot claim two blocks and skip
            # beyond the finite cursor, even with only two Run identities.
            lines = tail.decode('utf8').splitlines()
            for index, line in enumerate(lines):
                event = json.loads(line)
                if event['kind'] == 'wave_reserved' and event['pairs'] == [100]:
                    event['blocks'] = 2; lines[index] = json.dumps(event); break
            d.journal.write_text('\n'.join(lines) + '\n', encoding='utf8')
            with self.assertRaises(ValueError): d.current()
            d.journal.write_bytes(tail)


if __name__ == '__main__': unittest.main()
