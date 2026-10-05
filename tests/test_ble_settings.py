"""Verify a saved BLE address takes effect without restarting the gateway."""
import asyncio
from contextlib import suppress
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from iot_fixture import load_iot


class BleSettingsTests(unittest.TestCase):
    def test_mac_change_reconnects_only_the_selected_node(self):
        iot = load_iot()
        node = {'room': 'patient', 'mac': 'AA:00:00:00:00:01',
                'notify_uuid': 'notify', 'command_uuid': 'command'}
        selected = ['AA:00:00:00:00:01']
        iot.get_config_value = Mock(side_effect=lambda _key, _default: selected[0])
        iot.set_node_online = Mock()
        iot._resync_safety = Mock()
        iot._send_pending = AsyncMock()
        iot.BLE_RECONNECT_DELAY = 0.01
        iot.enqueue_command('patient', '{"cmd":"fan","state":1}')
        addresses = []

        async def scenario():
            first, second = asyncio.Event(), asyncio.Event()

            class Client:
                def __init__(self, mac):
                    self.mac = mac
                    self.is_connected = True

                async def __aenter__(self):
                    addresses.append(self.mac)
                    (first if len(addresses) == 1 else second).set()
                    return self

                async def __aexit__(self, *_args):
                    self.is_connected = False

                async def start_notify(self, *_args):
                    pass

            iot.BleakClient = Client
            task = asyncio.create_task(iot._node_loop(node))
            try:
                await asyncio.wait_for(first.wait(), 1)
                selected[0] = 'AB:CD:EF:01:23:45'
                iot.reconnect_ble_node('patient')
                await asyncio.wait_for(second.wait(), 2)
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

        asyncio.run(scenario())
        self.assertEqual(addresses[:2], ['AA:00:00:00:00:01', 'AB:CD:EF:01:23:45'])
        self.assertFalse(iot._pending_commands['patient'])
        self.assertFalse(iot._ble_reconfigure['living'].is_set())
        self.assertFalse(iot._ble_reconfigure['kitchen'].is_set())

    def test_scan_returns_names_and_addresses(self):
        iot = load_iot()
        iot.BleakScanner.discover = AsyncMock(return_value=[
            SimpleNamespace(name='ESP Kitchen', address='ab:cd:ef:01:23:45'),
            SimpleNamespace(name=None, address='aa:00:00:00:00:01'),
        ])
        self.assertEqual(asyncio.run(iot._scan_ble_devices()), [
            {'name': 'ESP Kitchen', 'mac': 'AB:CD:EF:01:23:45'},
            {'name': 'Thiết bị BLE', 'mac': 'AA:00:00:00:00:01'},
        ])

    def test_node_waits_for_mac_then_connects(self):
        iot = load_iot()
        iot.BLE_RECONNECT_DELAY = 0.01
        selected = ['']
        iot.get_config_value = Mock(side_effect=lambda _key, _default: selected[0])
        iot.set_node_online = Mock()
        iot._resync_safety = Mock()
        iot._send_pending = AsyncMock()
        addresses = []

        async def scenario():
            connected = asyncio.Event()

            class Client:
                def __init__(self, mac):
                    self.is_connected = True
                    addresses.append(mac)

                async def __aenter__(self):
                    connected.set()
                    return self

                async def __aexit__(self, *_args):
                    self.is_connected = False

                async def start_notify(self, *_args):
                    pass

            iot.BleakClient = Client
            task = asyncio.create_task(iot._node_loop({
                'room': 'living', 'mac': '', 'notify_uuid': 'notify',
                'command_uuid': 'command',
            }))
            try:
                await asyncio.sleep(0.03)
                self.assertFalse(addresses)
                selected[0] = 'AB:CD:EF:01:23:45'
                iot.reconnect_ble_node('living')
                await asyncio.wait_for(connected.wait(), 1)
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

        asyncio.run(scenario())
        self.assertEqual(addresses, ['AB:CD:EF:01:23:45'])
