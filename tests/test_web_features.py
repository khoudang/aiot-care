"""Exercise web startup and controls with a temporary DB and no hardware."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class WebFeaturesTests(unittest.TestCase):
    def setUp(self):
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
        self.iot = Mock()
        modules = patch.dict(sys.modules, {
            'config': config, 'iot': self.iot,
            'chatbot_system': None, 'medical_rag': None,
        })
        modules.start()
        self.addCleanup(modules.stop)
        for name in ('database', 'web', 'app'):
            spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        self.app = module.app
        self.app.config['TESTING'] = True
        self.socketio = module.socketio
        self.client = self.app.test_client()

    def login(self, username='test-admin'):
        response = self.client.post('/login', data={
            'username': username, 'password': 'test-password',
        })
        self.assertEqual(response.status_code, 302)

    def test_removed_endpoints_and_dashboard_for_both_roles(self):
        self.iot.start_background_services.assert_called_once()
        for username in ('test-admin', 'test-member'):
            self.login(username)
            response = self.client.get('/dashboard')
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertNotIn('family-doctor', html)
            self.assertNotIn('Hỏi trợ lý', html)
            self.assertEqual('id="ble-list"' in html, username == 'test-admin')
            for room in ('patient', 'living', 'kitchen'):
                self.assertIn('id="' + room + '"', html)
            for endpoint, method in (
                ('/api/chatbot', 'POST'), ('/api/chatbot/result/test', 'GET'),
                ('/api/medical_chat', 'POST'), ('/api/medical_chat/result/test', 'GET'),
            ):
                self.assertEqual(self.client.open(endpoint, method=method).status_code, 404)
            self.client.get('/logout')

    def test_authenticated_device_controls_still_reach_gateway(self):
        self.login()
        socket = self.socketio.test_client(self.app, flask_test_client=self.client)
        self.addCleanup(socket.disconnect)
        self.assertTrue(socket.is_connected())
        for room, device in (('patient', 'fan'), ('living', 'light'), ('kitchen', 'buzzer')):
            socket.emit('set_device', {'room': room, 'device': device, 'state': True})
            self.iot.set_device.assert_called_with(
                room=room, device=device, state=True, value=None,
                source='manual', user_id=1,
            )
        self.iot.set_camera_mode.return_value = {'active': False, 'mode': 'off'}
        socket.emit('set_camera_mode', {'mode': 'off'})
        self.iot.set_camera_mode.assert_called_with('off', user_id=1)

    def test_login_is_still_required(self):
        self.assertEqual(self.client.get('/dashboard').status_code, 302)
        socket = self.socketio.test_client(self.app, flask_test_client=self.client)
        self.assertFalse(socket.is_connected())

    def test_ble_mac_admin_only_validation_and_persistence(self):
        def nodes():
            from database import get_config_value
            return [
                {'room': room, 'mac': get_config_value('ble_mac_' + room, mac), 'online': False}
                for room, mac in (
                    ('patient', 'AA:00:00:00:00:01'),
                    ('living', 'AA:00:00:00:00:02'),
                    ('kitchen', 'AA:00:00:00:00:03'),
                )
            ]
        self.iot.ble_node_settings.side_effect = nodes
        url = '/api/admin/ble-nodes/patient'
        self.assertEqual(self.client.get('/api/admin/ble-nodes').status_code, 401)
        self.assertEqual(self.client.post(url, json={'mac': 'AB:CD:EF:01:23:45'}).status_code, 401)
        self.login('test-member')
        self.assertEqual(self.client.get('/api/admin/ble-scan').status_code, 403)
        self.assertEqual(self.client.post(url, json={'mac': 'AB:CD:EF:01:23:45'}).status_code, 403)
        self.client.get('/logout')
        self.login()
        self.assertEqual(self.client.post(url, json=['AB:CD:EF:01:23:45']).status_code, 400)
        self.assertEqual(self.client.post(url, json='AB:CD:EF:01:23:45').status_code, 400)
        self.assertEqual(self.client.post(url, json={'mac': 'invalid'}).status_code, 400)
        self.assertEqual(self.client.post(url, json={'mac': 'AA:00:00:00:00:02'}).status_code, 400)
        self.assertEqual(self.client.post('/api/admin/ble-nodes/other', json={'mac': 'AB:CD:EF:01:23:45'}).status_code, 404)
        self.iot.reconnect_ble_node.assert_not_called()
        response = self.client.post(url, json={'mac': 'ab:cd:ef:01:23:45'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['nodes'][0]['mac'], 'AB:CD:EF:01:23:45')
        self.iot.reconnect_ble_node.assert_called_once_with('patient')
        self.assertEqual(self.client.get('/api/admin/ble-nodes').json['nodes'][0]['mac'], 'AB:CD:EF:01:23:45')
        self.client.post(url, json={'mac': 'AB:CD:EF:01:23:45'})
        self.iot.reconnect_ble_node.assert_called_once()

    def test_ble_scan_is_admin_only_and_reports_failure(self):
        self.login()
        self.iot.scan_ble_devices.return_value = [{'name': 'ESP', 'mac': 'AB:CD:EF:01:23:45'}]
        self.assertEqual(self.client.get('/api/admin/ble-scan').json['devices'][0]['name'], 'ESP')
        self.iot.scan_ble_devices.side_effect = RuntimeError('Bluetooth adapter unavailable')
        response = self.client.get('/api/admin/ble-scan')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('Bluetooth adapter unavailable', response.get_data(as_text=True))
