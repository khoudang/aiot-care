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
