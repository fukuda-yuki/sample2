"""No model/process/filesystem validation outside synthetic fixtures."""
import unittest
from unittest.mock import Mock

from research.validation_scope import scoped_validation, validation_scope, validate_predecessor_once


class ValidationScopeTests(unittest.TestCase):
    def test_no_scope_means_full_validation_on_every_call(self):
        check = Mock(return_value=True)
        validate_predecessor_once('old-proof', check)
        validate_predecessor_once('old-proof', check)
        self.assertEqual(check.call_count, 2)

    def test_nested_operations_share_only_until_outer_exit(self):
        check = Mock(return_value=True)
        @scoped_validation
        def inner():
            return validate_predecessor_once('old-proof', check)
        @scoped_validation
        def outer():
            inner(); inner()
        outer()
        self.assertEqual(check.call_count, 1)
        outer()
        self.assertEqual(check.call_count, 2)
        inner()
        self.assertEqual(check.call_count, 3)

    def test_next_operation_rechecks_tampered_dependency_even_with_same_key(self):
        state = {'unchanged': True}
        def check():
            if not state['unchanged']:
                raise ValueError('Historical bytes changed')
            return True
        @scoped_validation
        def operation():
            return validate_predecessor_once('same-closure-reference', check)
        self.assertTrue(operation())
        state['unchanged'] = False
        with self.assertRaisesRegex(ValueError, 'Historical bytes changed'):
            operation()

    def test_changed_binding_key_is_not_reused_inside_operation(self):
        check = Mock(return_value=True)
        with validation_scope():
            validate_predecessor_once(('old-wave', 'hash-1'), check)
            validate_predecessor_once(('old-wave', 'hash-2'), check)
        self.assertEqual(check.call_count, 2)

    def test_exception_or_false_result_is_never_cached(self):
        check = Mock(side_effect=[ValueError('fault'), False, True])
        with validation_scope():
            with self.assertRaisesRegex(ValueError, 'fault'):
                validate_predecessor_once('old-proof', check)
            with self.assertRaisesRegex(ValueError, 'did not confirm'):
                validate_predecessor_once('old-proof', check)
            self.assertTrue(validate_predecessor_once('old-proof', check))
        self.assertEqual(check.call_count, 3)

    def test_pending_cycle_is_rejected_and_scope_is_reset_after_exception(self):
        def cycle():
            return validate_predecessor_once('old-proof', cycle)
        with self.assertRaisesRegex(ValueError, 'Cyclic'):
            with validation_scope():
                cycle()
        check = Mock(return_value=True)
        with validation_scope():
            self.assertTrue(validate_predecessor_once('old-proof', check))
        check.assert_called_once()

    def test_live_stop_usage_and_ownership_are_not_memoized(self):
        proof = Mock(return_value=True)
        live = {'stop': False, 'usage_exhausted': False, 'owner_lost': False}
        @scoped_validation
        def admission():
            validate_predecessor_once('old-proof', proof)
            if any(live.values()):
                raise ValueError('Live fault')
        for field in live:
            with self.subTest(field=field), validation_scope():
                admission()
                live[field] = True
                with self.assertRaisesRegex(ValueError, 'Live fault'):
                    admission()
                live[field] = False
        self.assertEqual(proof.call_count, 3)


if __name__ == '__main__':
    unittest.main()
