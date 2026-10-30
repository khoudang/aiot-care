"""Test in-memory command timing trace and latency observability."""
import asyncio
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from iot_fixture import load_iot


class BleLatencyTraceTests(unittest.TestCase):
    def setUp(self):
        self.iot = load_iot()

    def test_timing_trace_records_monotonic_deltas_and_lifecycle(self):
        iot = self.iot
        client = Mock(write_gatt_char=AsyncMock())
        t0 = 100.0

        with patch.object(iot.time, 'monotonic', return_value=t0):
            self.assertTrue(iot.enqueue_command('patient', '{"cmd":"fan","state":1,"value":50}'))

        stats = iot.get_command_timing_stats('patient')
        self.assertEqual(stats['total_commands'], 1)
        self.assertEqual(stats['queue_lengths']['patient'], 1)
        self.assertEqual(stats['recent_traces'][0]['status'], 'enqueued')

        t_write_start = t0 + 0.015  # 15 ms in queue
        with patch.object(iot.time, 'monotonic', return_value=t_write_start):
            asyncio.run(iot._send_pending('patient', client, 'uuid'))

        t_ack = t_write_start + 0.030  # 30 ms GATT + firmware ACK
        with patch.object(iot.time, 'monotonic', return_value=t_ack):
            handler = iot._make_notify_handler('patient')
            handler(None, json.dumps({'ack': 1, 'status': 'applied'}).encode())

        t_applied = t_ack + 0.005  # 5 ms immediate state telemetry
        with patch.object(iot.time, 'monotonic', return_value=t_applied):
            iot.apply_node_payload('patient', {'fan': True, 'fan_speed': 50})

        final_stats = iot.get_command_timing_stats('patient')
        self.assertEqual(final_stats['total_commands'], 1)
        self.assertEqual(final_stats['errors'], 0)
        self.assertEqual(final_stats['error_rate'], 0.0)
        self.assertEqual(final_stats['source'], 'simulated_host_timing_monotonic')

        # Verify monotonic calculation deltas:
        self.assertAlmostEqual(final_stats['queue_latency']['median_ms'], 15.0, places=1)
        self.assertAlmostEqual(final_stats['ack_rtt_latency']['median_ms'], 30.0, places=1)
        self.assertAlmostEqual(final_stats['total_latency']['median_ms'], 45.0, places=1)
        self.assertEqual(final_stats['recent_traces'][0]['status'], 'ack_applied')

    def test_timing_trace_tracks_errors_and_timeouts(self):
        iot = self.iot
        client = Mock(write_gatt_char=AsyncMock())

        with patch.object(iot.time, 'monotonic', return_value=10.0):
            iot.enqueue_command('living', '{"cmd":"light","state":1}')

        # Attempt 1
        with patch.object(iot.time, 'monotonic', return_value=10.05):
            asyncio.run(iot._send_pending('living', client, 'uuid'))

        # Timeout after attempts exhausted (time > TTL or attempts >= COMMAND_ATTEMPTS)
        for tick in range(12, 22, 2):
            with patch.object(iot.time, 'monotonic', return_value=float(tick)):
                asyncio.run(iot._send_pending('living', client, 'uuid'))

        stats = iot.get_command_timing_stats('living')
        self.assertEqual(stats['total_commands'], 1)
        self.assertEqual(stats['errors'], 1)
        self.assertEqual(stats['error_rate'], 1.0)
        self.assertIn('timeout', stats['recent_traces'][0]['status'].lower())

    def test_admin_timing_trace_endpoint_authorization(self):
        import importlib.util
        from pathlib import Path
        import sys
        import tempfile
        import types

        root = Path(__file__).resolve().parents[1]
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        config = types.ModuleType('config')
        config.SECRET_KEY = 'test-session-only'
        config.ALLOW_REGISTER = False
        config.DATABASE = str(Path(temporary.name) / 'test.db')
        config.DEFAULT_CONFIGS = {}
        config.INITIAL_USERS = [
            {'username': 'test-admin', 'password': 'test-password', 'role': 'admin'},
            {'username': 'test-member', 'password': 'test-password', 'role': 'member'},
        ]

        modules = patch.dict(sys.modules, {
            'config': config, 'iot': self.iot,
            'chatbot_system': None, 'medical_rag': None,
        })
        modules.start()
        self.addCleanup(modules.stop)

        for name in ('database', 'web', 'app'):
            spec = importlib.util.spec_from_file_location(name, root / (name + '.py'))
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)

        app = module.app
        app.config['TESTING'] = True
        test_client = app.test_client()

        # Unauthenticated request MUST be rejected
        unauth_resp = test_client.get('/api/admin/ble/timing-traces')
        self.assertEqual(unauth_resp.status_code, 401)  # Unauthorized JSON

        # Member role MUST be forbidden
        member_client = app.test_client()
        member_client.post('/login', data={'username': 'test-member', 'password': 'test-password'})
        member_resp = member_client.get('/api/admin/ble/timing-traces')
        self.assertEqual(member_resp.status_code, 403)

        # Admin role is allowed and receives structured JSON
        admin_client = app.test_client()
        admin_client.post('/login', data={'username': 'test-admin', 'password': 'test-password'})
        admin_resp = admin_client.get('/api/admin/ble/timing-traces')
        self.assertEqual(admin_resp.status_code, 200)
        data = admin_resp.get_json()
        self.assertTrue(data['ok'])
        self.assertIn('timing_trace', data)
        self.assertEqual(data['timing_trace']['source'], 'simulated_host_timing_monotonic')

    def test_tracer_and_active_bounded_above_200_items(self):
        """Both _traces deque and _active dict must be bounded (e.g. <= 200 items)."""
        iot = self.iot
        tracer = iot.timing_tracer
        # Enqueue 250 commands without ACKs
        for i in range(1, 251):
            tracer.record_enqueued('patient', i, 'fan', {'state': 1, 'value': i % 100})

        self.assertLessEqual(len(tracer._traces), 200)
        self.assertLessEqual(len(tracer._active), 200)

    def test_unsolicited_old_telemetry_before_write_does_not_apply_command(self):
        """Unsolicited telemetry before command write/ACK must NOT falsely mark command applied."""
        iot = self.iot
        iot.timing_tracer.record_enqueued('patient', 99, 'fan', {'state': 1, 'value': 80})

        # Unsolicited telemetry arrives before write starts or ACK
        iot.apply_node_payload('patient', {'fan': True, 'fan_speed': 80})

        # Command must still be active and status must NOT be applied_state
        stats = iot.get_command_timing_stats('patient')
        rec = next(r for r in stats['recent_traces'] if r['id'] == 99)
        self.assertNotEqual(rec['status'], 'applied_state')
        self.assertEqual(rec['status'], 'enqueued')

    def test_rejected_and_canceled_trace_cleanup(self):
        """Canceled and rejected commands must achieve terminal status and be removed from _active."""
        iot = self.iot
        tracer = iot.timing_tracer

        # Enqueue commands
        iot.enqueue_command('patient', '{"cmd":"fan","state":1,"value":40}')
        iot.enqueue_command('patient', '{"cmd":"fan","state":1,"value":60}')

        # _cancel_commands should mark canceled and clear from active
        iot._cancel_commands('patient', 'fan')
        self.assertEqual(len(tracer._active), 0)

        # Enqueue another and reject via ACK
        iot.enqueue_command('living', '{"cmd":"light","state":1}')
        cid = list(tracer._active.keys())[0][1]
        handler = iot._make_notify_handler('living')
        handler(None, json.dumps({'ack': cid, 'status': 'rejected'}).encode())

        self.assertNotIn(('living', cid), tracer._active)
        rec = next(r for r in tracer._traces if r['id'] == cid)
        self.assertEqual(rec['status'], 'ack_rejected')

    def test_ack_arriving_during_write_not_overwritten_by_write_done(self):
        """ACK arriving during write must not be overwritten by subsequent write_done callback."""
        iot = self.iot
        tracer = iot.timing_tracer
        tracer.record_enqueued('patient', 10, 'light', {'state': 1})
        tracer.record_write_start('patient', 10, 1)

        # ACK arrives while write is still completing in background
        tracer.record_ack('patient', 10, 'applied')
        self.assertEqual(tracer._traces[-1]['status'], 'ack_applied')

        # write_done completes subsequently
        tracer.record_write_done('patient', 10)
        # Must retain terminal ack_applied, NOT reverted to written
        self.assertEqual(tracer._traces[-1]['status'], 'ack_applied')

    def test_get_summary_returns_snapshot_copies(self):
        """get_summary must return detached copies so external mutation doesn't alter internal records."""
        iot = self.iot
        tracer = iot.timing_tracer
        tracer.record_enqueued('patient', 42, 'buzzer', {'state': 1})
        summary = tracer.get_summary('patient')

        # Mutate the returned summary
        summary['recent_traces'][0]['status'] = 'MUTATED'

        # Fetch again: internal record must not be mutated
        summary2 = tracer.get_summary('patient')
        self.assertNotEqual(summary2['recent_traces'][0]['status'], 'MUTATED')


if __name__ == '__main__':
    unittest.main()
