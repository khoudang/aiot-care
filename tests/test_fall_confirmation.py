"""Fall confirmation must remain visible after the AI suspicion clears."""
import unittest
from unittest.mock import Mock
from pathlib import Path
import sys

# Ensure test directory is in path whether run directly or discovered
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # Load once before iot_fixture temporarily patches sys.modules.
from iot_fixture import load_iot

class FallConfirmationTests(unittest.TestCase):
    def test_snapshot_exposes_latched_fall_even_with_normal_kitchen(self):
        iot = load_iot()
        iot._fall_buzzer_saved = False
        iot.AI['fall'] = False
        iot.NODE_ONLINE['patient'] = True
        state = iot.snapshot_all()
        self.assertEqual(state['alert']['level'], 'normal')
        self.assertIn('fall_confirmation', state)
        status = state['fall_confirmation']
        self.assertTrue(status['required'])
        self.assertTrue(status['can_confirm'])
        self.assertFalse(status['active'])
        iot.AI['fall'] = True
        self.assertFalse(iot.snapshot_all()['fall_confirmation']['can_confirm'])
        iot.AI['fall'] = False
        iot._fall_restore_target = False
        self.assertTrue(iot.snapshot_all()['fall_confirmation']['pending'])
        self.assertFalse(iot.snapshot_all()['fall_confirmation']['can_confirm'])
        iot._fall_buzzer_saved = None
        iot._fall_restore_target = None
        self.assertFalse(iot.snapshot_all()['fall_confirmation']['required'])

    def test_patient_confirmation_waits_for_node_telemetry_before_unlocking(self):
        iot = load_iot()
        iot._fall_buzzer_saved = False
        iot.NODE_ONLINE['patient'] = True
        self.assertTrue(hasattr(iot, 'confirm_fall_safe'))
        self.assertTrue(iot.confirm_fall_safe(user_id=9))
        self.assertIs(iot._fall_restore_target, False)
        self.assertIs(iot._fall_buzzer_saved, False)
        self.assertTrue(iot.snapshot_all()['fall_confirmation']['pending'])
        iot.set_device('patient', 'buzzer', state=False, silent=True)
        self.assertIn('khóa', iot._emit.call_args.args[1]['message'])
        # Premature telemetry report while command delivery is still pending does not clear latch
        iot._pending_commands['patient']['cmd-pending'] = {'text': '{}'}
        iot._observe_fall_restoration('patient', {'buzzer': False})
        self.assertTrue(iot.snapshot_all()['fall_confirmation']['pending'])
        # Once pending commands clear and node telemetry confirms restored buzzer, latch releases
        iot._pending_commands['patient'].clear()
        iot._observe_fall_restoration('patient', {'buzzer': False})
        self.assertFalse(iot.snapshot_all()['fall_confirmation']['required'])
        self.assertFalse(iot.snapshot_all()['fall_confirmation']['pending'])
        self.assertFalse(iot.snapshot_all()['fall_confirmation']['can_confirm'])
        iot.set_device('patient', 'buzzer', state=True, silent=True)
        self.assertEqual(len(iot._pending_commands['patient']), 1)

    def test_patient_confirmation_never_acknowledges_a_kitchen_alert(self):
        iot = load_iot()
        iot._fall_buzzer_saved = False
        iot.NODE_ONLINE['patient'] = True
        iot._emergency_snapshot = {'patient': dict(iot.ROOMS['patient'])}
        iot.set_device = Mock()
        self.assertTrue(hasattr(iot, 'confirm_fall_safe'))
        self.assertFalse(iot.confirm_fall_safe(user_id=9))
        iot.set_device.assert_not_called()
        self.assertIsNone(iot._fall_restore_target)
        iot._emergency_snapshot = None
        iot.AI['fall'] = True
        self.assertFalse(iot.confirm_fall_safe(user_id=9))
        iot.set_device.assert_not_called()

    def test_patient_confirmation_blocks_when_node_offline(self):
        iot = load_iot()
        iot._fall_buzzer_saved = False
        iot.AI['fall'] = False
        iot.NODE_ONLINE['patient'] = False
        status = iot.snapshot_all()['fall_confirmation']
        self.assertTrue(status['required'])
        self.assertFalse(status['node_online'])
        self.assertFalse(status['can_confirm'])
        self.assertFalse(iot.confirm_fall_safe(user_id=9))
        self.assertIsNone(iot._fall_restore_target)

if __name__ == '__main__':
    unittest.main()
