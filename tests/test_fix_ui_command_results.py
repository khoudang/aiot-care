"""Correlate fix_ui pending controls with real BLE acknowledgements, not optimistic state."""
import json
import unittest
import numpy as np  # Load C extensions before load_iot's temporary sys.modules patch.
from iot_fixture import load_iot

class FixUiCommandResultTests(unittest.TestCase):
    def setUp(self):
        self.iot = load_iot()

    def queue(self, request_id: object='ui-request-1'):
        self.iot.set_device('living', 'light', state=True, silent=True, request_id=request_id)
        pending = self.iot._pending_commands['living']
        self.assertEqual(len(pending), 1)
        ident = next(iter(pending))
        return ident, json.loads(pending[ident]['text'])

    def test_request_id_is_preserved_without_confirming_a_command(self):
        _, command = self.queue()
        self.assertEqual(command['request_id'], 'ui-request-1')
        self.assertFalse(any(call.args[0] == 'command_result' for call in self.iot._emit.call_args_list))

    def test_matching_ack_emits_correlated_result(self):
        for status in ('applied', 'rejected'):
            with self.subTest(status=status):
                self.setUp()
                ident, _ = self.queue()
                self.iot._make_notify_handler('living')(None, bytearray(json.dumps(
                    {'room': 'living', 'ack': ident, 'status': status}).encode()))
                self.iot._emit.assert_any_call('command_result', {
                    'room': 'living', 'device': 'light',
                    'request_id': 'ui-request-1', 'status': status})
                self.assertNotIn(ident, self.iot._pending_commands['living'])

    def test_unknown_ack_cannot_confirm_pending_control(self):
        ident, _ = self.queue()
        self.iot._emit.reset_mock()
        self.iot._make_notify_handler('living')(None, bytearray(json.dumps(
            {'room': 'living', 'ack': ident + 1, 'status': 'applied'}).encode()))
        self.assertFalse(any(call.args[0] == 'command_result' for call in self.iot._emit.call_args_list))
        self.assertIn(ident, self.iot._pending_commands['living'])

    def test_invalid_request_ids_are_not_forwarded_to_firmware(self):
        for request_id in (None, 123, 'x' * 81):
            with self.subTest(request_id=repr(request_id)[:30]):
                self.setUp()
                _, command = self.queue(request_id)
                self.assertNotIn('request_id', command)

if __name__ == '__main__':
    unittest.main()
