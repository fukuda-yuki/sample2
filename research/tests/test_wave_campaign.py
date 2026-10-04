"""Offline controller wiring tests; no models, Docker or network."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from outer.harness import util
from research import wave_campaign as campaign


class DriverTests(unittest.TestCase):
    def dispatcher(self):
        d = Mock()
        d.current.return_value = {'waves': [], 'gates': {}}
        return d

    def test_review_wait_does_not_dispatch_or_recover_again(self):
        d = self.dispatcher()
        d.execute_next.return_value = {'status': 'held', 'reason': 'publication_review_pending'}
        d.finish_wave.side_effect = [dict(d.execute_next.return_value), {'status': 'wave_gated', 'pairs': [6, 7]}]
        sleeps = []
        result = campaign.drive(d, one_wave=True, sleep=sleeps.append)
        self.assertEqual(result['status'], 'wave_gated')
        self.assertEqual(sleeps, [5, 5])
        d.execute_next.assert_called_once()
        d.recover.assert_not_called()
        d.fault.assert_not_called()

    def test_operational_hold_does_not_poll_or_dispatch_more(self):
        d = self.dispatcher()
        d.execute_next.return_value = {'status': 'held', 'reason': 'durable_dispatch_stop'}
        sleep = Mock()
        self.assertEqual(campaign.drive(d, sleep=sleep)['reason'], 'durable_dispatch_stop')
        sleep.assert_not_called()
        d.execute_next.assert_called_once()

    def test_only_complete_wave_allows_next_dispatch(self):
        d = self.dispatcher()
        d.execute_next.side_effect = [{'status': 'wave_gated'}, {'status': 'complete'}]
        self.assertEqual(campaign.drive(d)['status'], 'complete')
        self.assertEqual(d.execute_next.call_count, 2)

    def test_recovery_review_poll_retains_recovery_mode_without_new_send(self):
        d = self.dispatcher()
        d.recover.return_value = {'status': 'held', 'reason': 'publication_review_pending'}
        d.finish_wave.return_value = {'status': 'wave_gated'}
        campaign.drive(d, mode='recover', sleep=lambda _: None)
        d.finish_wave.assert_called_once_with(recovering=True)
        d.execute_next.assert_not_called()

    def test_warmup_requires_distinct_resource_samples(self):
        health = Mock()
        health.snapshot.side_effect = [{'sampled_at': s} for s in ('a', 'a', 'b')]
        with patch.object(campaign.wave_plan, 'healthy', return_value=True):
            self.assertTrue(campaign.warmup(health, {}, sleep=lambda _: None, clock=lambda: 0))
        self.assertEqual(health.snapshot.call_count, 3)


class JournalTests(unittest.TestCase):
    def test_identity_and_provider_failure_hold_without_raw_response_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'A'
            util.write_new_json(root / 'manifest.json', {'run_id': 'A', 'run_instance_id': 'instance-A'})
            binding = {'run_id': 'A', 'run_instance_id': 'instance-A'}
            event = {'run_id': 'A', 'session_id': 'instance-A', 'request_id': 'request-1'}
            util.append_line(root / 'usage/raw/started.jsonl', event)
            value = campaign.journal_health(directory, [binding], 'fixed-model')
            self.assertTrue(value['journal_healthy'])
            self.assertEqual(value['http_inflight_max'], 1)
            util.append_line(root / 'usage/raw/events.jsonl', {**event, 'session_id': 'foreign',
                'model_id': 'other-model', 'status': 'transport_error'})
            value = campaign.journal_health(directory, [binding], 'fixed-model')
            self.assertFalse(value['journal_healthy'])
            self.assertFalse(value['provider_healthy'])

    def test_final_usage_missing_terminal_is_not_zero_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'A'
            util.write_new_json(root / 'manifest.json', {'run_id': 'A', 'run_instance_id': 'i', 'stop_confirmed': True})
            util.append_line(root / 'usage/raw/started.jsonl', {'run_id': 'A', 'session_id': 'i', 'request_id': 'r'})
            value = campaign.journal_health(directory, [{'run_id': 'A', 'run_instance_id': 'i'}], 'm')
            self.assertFalse(value['http_healthy'])


class StorageTests(unittest.TestCase):
    def test_resource_scope_waits_for_durable_worker_creation_milestone(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'A'
            binding = {'run_id': 'A', 'run_instance_id': 'i'}
            util.write_new_json(root / 'manifest.json', binding)
            util.write_new_json(root / 'runtime.json', binding)
            d = Mock(); d.batch = Path(directory)
            d.current.return_value = {'waves': [{'pairs': [6, 7], 'assignments': [binding]}], 'dispatch': {'A': binding}}
            monitor = Mock()
            health = campaign.Health(d, monitor)
            self.assertEqual(health.roots(), [])
            util.write_json_atomic(root / 'runtime.json', {**binding, 'worker_started_at': 'created'})
            self.assertEqual(health.roots(), [root])
            monitor.set_wave.assert_called_with('wave-6-7', 1)

    def test_first_wave_forecast_reserves_all_remaining_not_just_active_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'policy.json'
            gib = 1024 ** 3
            util.write_new_json(path, {'disk': {'initial_retained_bytes_per_remaining_pair': 1.5*gib,
                'scratch_bytes_per_next_or_unfixed_wave_pair': 4*gib, 'hard_free_floor_bytes': 10*gib}})
            d = Mock(); d.phase = {'operational_policy': {'path': str(path)},
                'assignments': [None]*95, 'two_pair_blocks': [[6, 7]]}
            health = campaign.Health(d, Mock())
            value = health.disk_forecast({'waves': [], 'gates': {}, 'block_cursor': 0},
                {'disk_free_min_bytes': 160*gib, 'escalation_healthy': False})
            self.assertEqual(value['required_free_bytes'], 160.5*gib)
            self.assertFalse(value['healthy'])


if __name__ == '__main__': unittest.main()
