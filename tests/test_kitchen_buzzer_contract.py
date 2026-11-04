"""Kitchen buzzer contract: no real BLE/UART/camera access."""
import json,unittest
import numpy as np
from iot_fixture import load_iot

class KitchenBuzzerContractTests(unittest.TestCase):
 def setUp(self):self.iot=load_iot()
 def test_normal_on_off_are_queued_and_only_node_updates_state(self):
  for desired in [True,False]:
   with self.subTest(desired=desired):
    self.setUp();iot=self.iot;iot.ROOMS['kitchen']['buzzer']=not desired
    iot.set_device('kitchen','buzzer',state=desired,request_id='kitchen-buzzer-test',silent=True)
    self.assertEqual(iot.ROOMS['kitchen']['buzzer'],not desired)
    self.assertEqual(len(iot._pending_commands['kitchen']),1)
    ident=next(iter(iot._pending_commands['kitchen']))
    iot._make_notify_handler('kitchen')(None,json.dumps({'room':'kitchen','ack':ident,'status':'applied'}).encode())
    iot._emit.assert_any_call('command_result',{'room':'kitchen','device':'buzzer','request_id':'kitchen-buzzer-test','status':'applied'})
    self.assertEqual(iot.ROOMS['kitchen']['buzzer'],not desired,'ACK alone is not telemetry')
    iot.apply_node_payload('kitchen',{'buzzer':desired})
    self.assertEqual(iot.ROOMS['kitchen']['buzzer'],desired)
 def test_latched_emergency_still_rejects_manual_commands(self):
  iot=self.iot;iot._emergency_snapshot={r:dict(d) for r,d in iot.ROOMS.items()}
  for desired in [True,False]:
   iot.set_device('kitchen','buzzer',state=desired,request_id='blocked-test',silent=True)
  self.assertEqual(len(iot._pending_commands['kitchen']),0)
  self.assertTrue(any(c.args[0]=='command_error' for c in iot._emit.call_args_list))

if __name__=='__main__':unittest.main()
