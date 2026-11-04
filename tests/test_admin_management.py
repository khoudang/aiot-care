"""Real Flask/SQLite admin API tests; never import app.py or start hardware."""
import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import Mock

import pytest
from flask import Flask
from werkzeug.security import check_password_hash

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def admin_app(tmp_path, monkeypatch):
    config = types.ModuleType('config')
    config.ALLOW_REGISTER = False
    config.DATABASE = str(tmp_path / 'admin-test.sqlite')
    config.DEFAULT_CONFIGS = {}
    config.INITIAL_USERS = []
    monkeypatch.setitem(sys.modules, 'config', config)
    monkeypatch.setitem(sys.modules, 'iot', Mock())
    modules = {}
    for name in ('database', 'web'):
        spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        modules[name] = module
    db = modules['database']
    db.init_db()
    db.create_user('fixture-admin', 'fixture-password', 'admin')
    db.create_user('fixture-member', 'fixture-password', 'member')
    app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    app.config.update(TESTING=True, SECRET_KEY='isolated-test-only')
    modules['web'].register_web(app, Mock())
    return app, db


def sign_in(client, user_id=1):
    with client.session_transaction() as session:
        session['user_id'] = user_id


def test_admin_create_member(admin_app):
    app, db = admin_app
    client = app.test_client()
    sign_in(client)
    response = client.post('/api/admin/users', json={'username': ' new-member ', 'password': 'new-password'})
    assert response.status_code == 201
    assert response.json['ok'] is True
    user = db.get_user_by_username('new-member')
    assert user['role'] == 'member'
    assert check_password_hash(user['password_hash'], 'new-password')
    assert 'password_hash' not in str(response.json)


def test_existing_lock_unlock_delete_and_protection(admin_app):
    app, db = admin_app
    client = app.test_client()
    sign_in(client)
    assert client.post('/api/admin/users/1/suspend').status_code == 400
    assert client.delete('/api/admin/users/1').status_code == 400
    member = app.test_client()
    sign_in(member, 2)
    db.log_login(2, '127.0.0.1')
    db.log_audit('fixture activity', 2)
    assert client.post('/api/admin/users/2/suspend').status_code == 200
    assert db.get_user_by_id(2)['is_suspended'] == 1
    assert member.get('/dashboard').status_code == 302
    assert client.post('/api/admin/users/2/suspend').status_code == 200
    assert db.get_user_by_id(2)['is_suspended'] == 0
    sign_in(member, 2)
    assert member.get('/dashboard').status_code == 200
    assert client.delete('/api/admin/users/2').status_code == 200
    assert db.get_user_by_id(2) is None
    assert member.get('/dashboard').status_code == 302
    assert client.delete('/api/admin/users/999').status_code == 404
    assert client.post('/api/admin/users/999/suspend').status_code == 404


@pytest.mark.parametrize('payload', [None, [], 'bad', {}, {'username': 12, 'password': 'abcdef'},
    {'username': 'ab', 'password': 'abcdef'}, {'username': 'valid', 'password': []},
    {'username': 'valid', 'password': 'short'},
    {'username': 'valid', 'password': 'abcdef', 'role': 'admin'}])
def test_create_validation(admin_app, payload):
    app, db = admin_app
    client = app.test_client()
    sign_in(client)
    response = client.post('/api/admin/users', json=payload)
    assert response.status_code == 400
    assert response.json['ok'] is False
    assert len(db.fetch_admin_users()) == 2


def test_duplicate_and_create_lock_unlock_delete_flow(admin_app):
    app, db = admin_app
    client = app.test_client()
    sign_in(client)
    payload = {'username': 'flow-member', 'password': 'fixture-password'}
    assert client.post('/api/admin/users', json=payload).status_code == 201
    assert client.post('/api/admin/users', json=payload).status_code == 409
    user_id = db.get_user_by_username('flow-member')['id']
    other = app.test_client()
    assert other.post('/login', data=payload).status_code == 302
    assert other.get('/dashboard').status_code == 200
    assert client.post(f'/api/admin/users/{user_id}/suspend').status_code == 200
    assert other.get('/dashboard').status_code == 302
    assert client.post(f'/api/admin/users/{user_id}/suspend').status_code == 200
    assert other.post('/login', data=payload).status_code == 302
    assert other.get('/dashboard').status_code == 200
    assert client.post(f'/api/admin/users/{user_id}/edit', json={'username': 'renamed-flow', 'password': ''}).status_code == 200
    assert check_password_hash(db.get_user_by_id(user_id)['password_hash'], payload['password'])
    assert client.delete(f'/api/admin/users/{user_id}').status_code == 200
    assert db.get_user_by_id(user_id) is None
    assert other.get('/dashboard').status_code == 302
    assert not any('fixture-password' in row['action'] for row in db.fetch_audit_logs())


@pytest.mark.parametrize('method,url', [('GET', '/api/admin/users'), ('POST', '/api/admin/users'),
    ('POST', '/api/admin/users/1/edit'), ('POST', '/api/admin/users/1/suspend'),
    ('DELETE', '/api/admin/users/1')])
def test_admin_mutation_auth(admin_app, method, url):
    app, db = admin_app
    client = app.test_client()
    assert client.open(url, method=method, json={}).status_code == 401
    sign_in(client, 2)
    assert client.open(url, method=method, json={}).status_code == 403
    sign_in(client, 1)
    with db.get_db_connection() as conn:
        conn.execute('update users set is_suspended = 1 where id = 1')
    assert client.open(url, method=method, json={}).status_code == 401


if __name__ == '__main__':
    # Optional isolated browser fixture; local only, no app.py and no real DB.
    import argparse
    import os
    import tempfile
    from flask import redirect, session
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5117)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='admin-browser-', dir=os.environ.get('TMPDIR')) as temporary:
        patcher = pytest.MonkeyPatch()
        try:
            app, db = admin_app.__wrapped__(Path(temporary), patcher)
            @app.get('/__test/admin-session')
            def test_admin_session():
                session['user_id'] = 1
                return redirect('/dashboard')
            app.run(host='127.0.0.1', port=args.port, debug=False, use_reloader=False)
        finally:
            patcher.undo()
