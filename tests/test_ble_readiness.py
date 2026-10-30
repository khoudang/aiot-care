"""Test BLE discovery, readiness, notify failure handling, and multi-node isolation."""
import asyncio
from contextlib import suppress
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from iot_fixture import load_iot


class BleReadinessTests(unittest.TestCase):
    def setUp(self):
        self.iot = load_iot()
        self.iot.BLE_RECONNECT_DELAY = 0.01

    def test_start_notify_failure_does_not_set_node_online(self):
        """Node must NOT be reported as ready if start_notify fails."""
        iot = self.iot
        node = {'room': 'living', 'mac': '11:22:33:44:55:66',
                'notify_uuid': 'notify', 'command_uuid': 'command'}

        iot.get_config_value = Mock(return_value='11:22:33:44:55:66')
        status_transitions = []
        original_set_online = iot.set_node_online

        def tracking_set_online(room, online, state=None):
            status_transitions.append((room, online, state or iot.NODE_STATES.get(room)))
            return original_set_online(room, online, state=state)

        iot.set_node_online = tracking_set_online

        class FaultyClient:
            def __init__(self, device):
                self.is_connected = True
                self.device = device

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                self.is_connected = False

            async def start_notify(self, *_args):
                raise RuntimeError("GATT subscription failed: Descriptor write rejected")

        iot.BleakClient = FaultyClient
        iot.BleakScanner.discover = AsyncMock(return_value=[
            SimpleNamespace(name='Living ESP', address='11:22:33:44:55:66')
        ])

        async def run_scenario():
            task = asyncio.create_task(iot._node_loop(node))
            try:
                await asyncio.sleep(0.08)
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

        asyncio.run(run_scenario())

        # The node must NEVER have achieved ready=True / online=True
        self.assertFalse(iot.NODE_ONLINE['living'])
        self.assertNotIn(('living', True, 'ready'), status_transitions)
        self.assertTrue(any(st[2] in ('connecting', 'subscribing') for st in status_transitions))
        self.assertEqual(iot.NODE_STATES['living'], 'disconnected')

    def test_empty_scan_then_appearing_device(self):
        """When scan initially returns empty, node waits then connects once device appears."""
        iot = self.iot
        iot.BLE_SCAN_CACHE_TTL = 0.02
        node = {'room': 'patient', 'mac': 'AA:BB:CC:DD:EE:01',
                'notify_uuid': 'notify', 'command_uuid': 'command'}
        iot.get_config_value = Mock(return_value='AA:BB:CC:DD:EE:01')

        connected = asyncio.Event()
        scan_count = 0

        async def mock_discover(**_kwargs):
            nonlocal scan_count
            scan_count += 1
            if scan_count < 2:
                return []
            return [SimpleNamespace(name='Patient ESP', address='AA:BB:CC:DD:EE:01')]

        iot.BleakScanner.discover = AsyncMock(side_effect=mock_discover)

        class SuccessClient:
            def __init__(self, device):
                self.is_connected = True
                self.device = device

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                self.is_connected = False

            async def start_notify(self, *_args):
                connected.set()

        iot.BleakClient = SuccessClient

        async def run_scenario():
            task = asyncio.create_task(iot._node_loop(node))
            try:
                await asyncio.wait_for(connected.wait(), timeout=1.5)
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

        asyncio.run(run_scenario())
        self.assertTrue(connected.is_set())
        self.assertTrue(scan_count >= 2)

    def test_one_node_down_while_others_remain_ready(self):
        """Failure/disconnect on one node must not compromise ready state of others."""
        iot = self.iot
        living_connected = asyncio.Event()
        patient_connected = asyncio.Event()

        class MockClient:
            def __init__(self, device):
                self.device = device
                self.is_connected = True

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                self.is_connected = False

            async def start_notify(self, notify_uuid, handler):
                if 'patient' in self.device.name.lower():
                    patient_connected.set()
                elif 'living' in self.device.name.lower():
                    living_connected.set()
                else:
                    raise ConnectionError("Kitchen offline")

        iot.BleakClient = MockClient
        iot.get_config_value = lambda key, default: {
            'ble_mac_patient': '00:00:00:00:00:01',
            'ble_mac_living': '00:00:00:00:00:02',
            'ble_mac_kitchen': '00:00:00:00:00:03',
        }.get(key, default)

        iot.BleakScanner.discover = AsyncMock(return_value=[
            SimpleNamespace(name='Patient Node', address='00:00:00:00:00:01'),
            SimpleNamespace(name='Living Node', address='00:00:00:00:00:02'),
            SimpleNamespace(name='Kitchen Node', address='00:00:00:00:00:03'),
        ])

        async def run_scenario():
            nodes = [
                {'room': 'patient', 'mac': '00:00:00:00:00:01', 'notify_uuid': 'n1', 'command_uuid': 'c1'},
                {'room': 'living', 'mac': '00:00:00:00:00:02', 'notify_uuid': 'n2', 'command_uuid': 'c2'},
                {'room': 'kitchen', 'mac': '00:00:00:00:00:03', 'notify_uuid': 'n3', 'command_uuid': 'c3'},
            ]
            tasks = [asyncio.create_task(iot._node_loop(n)) for n in nodes]
            try:
                await asyncio.wait_for(
                    asyncio.gather(patient_connected.wait(), living_connected.wait()),
                    timeout=1.5
                )
                await asyncio.sleep(0.05)
                # Patient and Living must be READY and ONLINE
                self.assertTrue(iot.NODE_ONLINE['patient'])
                self.assertEqual(iot.NODE_STATES['patient'], 'ready')
                self.assertTrue(iot.NODE_ONLINE['living'])
                self.assertEqual(iot.NODE_STATES['living'], 'ready')
                # Kitchen must be OFFLINE/DISCONNECTED
                self.assertFalse(iot.NODE_ONLINE['kitchen'])
                self.assertEqual(iot.NODE_STATES['kitchen'], 'disconnected')
            finally:
                for t in tasks:
                    t.cancel()
                for t in tasks:
                    with suppress(asyncio.CancelledError):
                        await t

        asyncio.run(run_scenario())

    def test_connected_node_preserved_in_discovery_cache_when_absent_from_advertisements(self):
        """Active connection must not be purged from discovery cache during rescan, without client._device."""
        iot = self.iot
        dev_patient = SimpleNamespace(name='Patient Node', address='00:00:00:00:00:01')
        iot._ble_devices['00:00:00:00:00:01'] = dev_patient
        # Realistic client with NEITHER _device nor device attribute
        client = SimpleNamespace(is_connected=True)
        self.assertFalse(hasattr(client, '_device'))
        self.assertFalse(hasattr(client, 'device'))
        iot.ble_clients['patient'] = client
        iot._connected_ble_devices['patient'] = dev_patient

        # New scan only finds living room; patient is not advertising because it is connected
        dev_living = SimpleNamespace(name='Living Node', address='00:00:00:00:00:02')
        iot.BleakScanner.discover = AsyncMock(return_value=[dev_living])

        devices = asyncio.run(iot._discover_ble_devices(force=True))
        addresses = {d.address.upper() for d in devices}

        self.assertIn('00:00:00:00:00:01', addresses)
        self.assertIn('00:00:00:00:00:02', addresses)
        self.assertEqual(iot._ble_devices['00:00:00:00:00:01'], dev_patient)

    def test_concurrent_missing_targets_cause_single_scan_within_ttl(self):
        """Concurrent lookups for missing devices must coordinate and run only ONE scan within TTL."""
        iot = self.iot
        iot._ble_devices.clear()
        iot._ble_devices_seen_at = 0.0

        scan_count = 0
        async def mock_discover(**_kwargs):
            nonlocal scan_count
            scan_count += 1
            await asyncio.sleep(0.02)
            return [SimpleNamespace(name='Some Node', address='11:11:11:11:11:11')]

        iot.BleakScanner.discover = AsyncMock(side_effect=mock_discover)

        async def run_lookups():
            # 3 concurrent requests for different missing MACs
            res = await asyncio.gather(
                iot._find_ble_device('22:22:22:22:22:22'),
                iot._find_ble_device('33:33:33:33:33:33'),
                iot._find_ble_device('44:44:44:44:44:44'),
            )
            return res

        asyncio.run(run_lookups())
        # Must execute exactly ONE scan, not 3 serialized scans
        self.assertEqual(scan_count, 1)

    def test_force_manual_scan_bypasses_cache_with_rate_limit(self):
        """Explicit manual scan bypasses normal cache but is bounded by rate limit."""
        iot = self.iot
        iot._ble_devices.clear()
        iot._ble_devices['AA:AA:AA:AA:AA:01'] = SimpleNamespace(name='Node 1', address='AA:AA:AA:AA:AA:01')
        iot._ble_devices_seen_at = 100.0
        iot._last_manual_scan_at = 0.0

        scan_count = 0
        async def mock_discover(**_kwargs):
            nonlocal scan_count
            scan_count += 1
            return [SimpleNamespace(name='Node 1', address='AA:AA:AA:AA:AA:01')]

        iot.BleakScanner.discover = AsyncMock(side_effect=mock_discover)

        # Normal find within TTL should NOT scan
        with patch.object(iot.time, 'monotonic', return_value=102.0):
            res1 = asyncio.run(iot._find_ble_device('AA:AA:AA:AA:AA:01'))
            self.assertEqual(scan_count, 0)

        # Explicit manual scan with force=True bypasses cache
        with patch.object(iot.time, 'monotonic', return_value=103.0):
            res2 = asyncio.run(iot._scan_ble_devices())
            self.assertEqual(scan_count, 1)
            self.assertEqual(len(res2), 1)

        # Immediate repeated manual scan within rate limit uses recent cache
        with patch.object(iot.time, 'monotonic', return_value=103.5):
            res3 = asyncio.run(iot._scan_ble_devices())
            self.assertEqual(scan_count, 1)  # rate-limited, no extra scan


if __name__ == '__main__':
    unittest.main()
