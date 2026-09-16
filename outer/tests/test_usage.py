"""Usage normalization rules. Ported invariants from sample1's normalizer."""
import unittest

try:
    from . import support  # noqa: F401  (puts outer/ on sys.path)
except ImportError:  # started as a top-level module (discover -s outer/tests)
    import support  # noqa: F401
from harness import usage


def event(session, event_id, request_id, input_tokens, output_tokens,
          mode='request', run_id='r1', includes_children=False):
    return {'run_id': run_id, 'session_id': session, 'event_id': event_id,
            'request_id': request_id, 'mode': mode,
            'usage': {'input_tokens': input_tokens, 'output_tokens': output_tokens},
            'includes_children': includes_children}


class NormalizeTest(unittest.TestCase):
    def test_complete_usage_gives_a_total(self):
        events = [event('a', 'e1', 'r1', 100, 10), event('a', 'e2', 'r2', 200, 20),
                  event('b', 'e1', 'r3', 5, 1)]
        result = usage.normalize(events, ['a', 'b'], True)
        self.assertTrue(result['usage_complete'])
        self.assertEqual(336, result['total_tokens'])
        self.assertEqual(336, result['observed_tokens'])
        self.assertEqual(3, result['observed_request_count'])
        self.assertEqual([], result['missing'])

    def test_missing_usage_is_not_replaced_by_zero(self):
        events = [event('a', 'e1', 'r1', None, None)]
        result = usage.normalize(events, ['a'], True)
        self.assertFalse(result['usage_complete'])
        self.assertIsNone(result['total_tokens'])
        self.assertEqual(0, result['observed_tokens'])
        # A session with no usable event counts as unobserved as well.
        self.assertEqual(['usage_missing', 'session_unobserved'],
                         [m['reason'] for m in result['missing']])

    def test_unobserved_session_is_missing(self):
        result = usage.normalize([event('a', 'e1', 'r1', 1, 1)], ['a', 'b'], True)
        self.assertFalse(result['usage_complete'])
        self.assertEqual(['session_unobserved'], [m['reason'] for m in result['missing']])

    def test_unverified_inventory_is_missing(self):
        result = usage.normalize([event('a', 'e1', 'r1', 1, 1)], ['a'], False)
        self.assertFalse(result['usage_complete'])
        self.assertIsNone(result['total_tokens'])
        self.assertEqual(2, result['observed_tokens'])
        self.assertIn('call_and_session_inventory_unverified',
                      [m['reason'] for m in result['missing']])

    def test_duplicate_request_is_counted_once(self):
        events = [event('a', 'e1', 'r1', 100, 10), event('a', 'e2', 'r1', 100, 10)]
        result = usage.normalize(events, ['a'], True)
        self.assertEqual(110, result['total_tokens'])
        self.assertEqual(1, result['observed_request_count'])

    def test_conflicting_duplicate_event_is_rejected(self):
        events = [event('a', 'e1', 'r1', 100, 10), event('a', 'e1', 'r1', 999, 9)]
        with self.assertRaises(ValueError):
            usage.normalize(events, ['a'], True)

    def test_conflicting_request_usage_is_rejected(self):
        events = [event('a', 'e1', 'r1', 100, 10), event('a', 'e2', 'r1', 5, 5)]
        with self.assertRaises(ValueError):
            usage.normalize(events, ['a'], True)

    def test_mixed_modes_in_one_session_are_rejected(self):
        events = [event('a', 'e1', 'r1', 100, 10),
                  event('a', 'e2', 'r2', 200, 20, mode='cumulative')]
        with self.assertRaises(ValueError):
            usage.normalize(events, ['a'], True)

    def test_cumulative_is_accumulated_by_difference(self):
        events = [event('a', 'e1', 'c1', 100, 10, mode='cumulative'),
                  event('a', 'e2', 'c2', 300, 40, mode='cumulative')]
        result = usage.normalize(events, ['a'], True)
        self.assertEqual(340, result['total_tokens'])
        self.assertEqual(['a'], result['cumulative_sessions'])

    def test_cumulative_decrease_is_rejected(self):
        events = [event('a', 'e1', 'c1', 300, 40, mode='cumulative'),
                  event('a', 'e2', 'c2', 100, 10, mode='cumulative')]
        with self.assertRaises(ValueError):
            usage.normalize(events, ['a'], True)

    def test_parent_inclusive_totals_are_rejected(self):
        events = [event('a', 'e1', 'r1', 1, 1, includes_children=True)]
        with self.assertRaises(ValueError):
            usage.normalize(events, ['a'], True)

    def test_unregistered_session_is_rejected(self):
        with self.assertRaises(ValueError):
            usage.normalize([event('z', 'e1', 'r1', 1, 1)], ['a'], True)

    def test_two_runs_cannot_be_combined(self):
        events = [event('a', 'e1', 'r1', 1, 1, run_id='r1'),
                  event('a', 'e2', 'r2', 1, 1, run_id='r2')]
        with self.assertRaises(ValueError):
            usage.normalize(events, ['a'], True)

    def test_events_from_another_run_are_rejected(self):
        """A single foreign run id is not "mixed": it is simply not this Run."""
        with self.assertRaises(ValueError):
            usage.normalize([event('a', 'e1', 'r1', 1, 1, run_id='r1')], ['a'], True,
                            run_id='r2')

    def test_matching_run_id_is_accepted(self):
        result = usage.normalize([event('a', 'e1', 'r1', 1, 1, run_id='r1')], ['a'], True,
                                 run_id='r1')
        self.assertTrue(result['usage_complete'])
        self.assertEqual('r1', result['run_id'])

    def test_negative_counts_are_rejected(self):
        with self.assertRaises(ValueError):
            usage.normalize([event('a', 'e1', 'r1', -1, 1)], ['a'], True)

    def test_float_counts_are_rejected(self):
        with self.assertRaises(ValueError):
            usage.normalize([event('a', 'e1', 'r1', 1.5, 1)], ['a'], True)


if __name__ == '__main__':
    unittest.main()
