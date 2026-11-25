"""Offline contracts for the headless service; all data is synthetic and temporary."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ['FITFLARE_AUTO_SYNC_ENABLED'] = 'false'
from server import PANEL_API_URL, PANEL_HEALTH_URL, create_app
from backend import jobs, sync
from common import profile_paths
from tests.fixture import make_fixture

READ_ONLY = {'GET', 'HEAD', 'OPTIONS'}
SECRET = 'synthetic-refresh-token-never-served'


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        make_fixture(self.root / 'profiles')
        (self.root / 'profiles/Demo/auth/tokens.json').write_text(json.dumps({'refresh_token': SECRET}))
        old_cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, old_cwd)
        patcher = patch.object(profile_paths, 'ROOT_DIR', str(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {'FITFLARE_PROFILE_ID': 'Demo', 'FITBIT_CLIENT_ID': '',
                                      'FITBIT_CLIENT_SECRET': '', 'FITBIT_TOKENS_FILE': ''})
        env.start()
        self.addCleanup(env.stop)
        self.config = dict(OWNER_PROFILE_ID='Demo', TESTING=True, PROFILES_DIR=str(self.root / 'profiles'))
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        jobs.fetch_jobs.clear()

    def files(self):
        return {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_health_check_stays_available_and_private(self):
        for method in ('GET', 'HEAD'):
            response = self.client.open('/api/health', method=method)
            self.assertEqual(response.status_code, 200)
            self.assertIn('no-store', response.headers['Cache-Control'])
        body = self.client.get('/api/health').json
        self.assertEqual(body['status'], 'healthy')
        self.assertEqual(body['active_jobs'], 0)
        self.assertFalse(body['auto_sync_enabled'])
        self.assertEqual(set(body), {'status', 'timestamp', 'active_jobs', 'auto_sync_enabled',
                                     'auto_sync_interval_seconds', 'auto_sync_scan_interval_seconds'})

    def test_old_pages_and_file_paths_redirect_to_the_panel_without_serving_files(self):
        for path in ('/', '/index.html', '/mobile.html', '/spousal.html', '/about.html', '/privacy.html', '/terms.html',
                     '/app.js', '/style.css', '/js/data.js', '/vendor/chart.umd-4.4.1.min.js', '/favicon.ico',
                     '/assets/favicon-32x32.png', '/?profile=Hidden', '/.env', '/.git/config', '/server.py',
                     '/backend/security.py', '/profiles/index.json', '/profiles/Demo/csv/example.csv',
                     '/profiles/Demo/auth/google_client.json', '/profiles/Demo/auth/tokens.json',
                     '/profiles/Demo/cache/dashboard.json', '/templates/public_api.html', '/static/server.py',
                     '/%2e%2e/server.py'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 301)
                self.assertEqual(response.headers['Location'], PANEL_HEALTH_URL)
                text = response.get_data(as_text=True)
                for leak in (SECRET, 'test-only', 'sleep_score', 'import ', 'Flask'):
                    self.assertNotIn(leak, text)

    def test_retired_api_answers_gone_with_a_pointer_and_no_data(self):
        for path in ('/api/', '/api/dashboard', '/api/dashboard/Demo', '/api/tables/Demo/sleep', '/api/profiles',
                     '/api/profile-summaries', '/api/account', '/api/public/v1/me', '/api/public/v1/me/dashboard',
                     '/api/public/v1/docs', '/api/public/v1/openapi.json', '/api/public/v1/profiles/Demo/series/daily',
                     '/api/public/v1/profiles/Demo/charts/overview-trend.svg', '/api/fetch-jobs', '/api/admin/session',
                     '/api/dashboard/%2e%2e', '/api/public/v1/me?profile=Hidden'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 410)
                self.assertEqual(response.json['code'], 'gone')
                self.assertEqual(response.json['see'], PANEL_API_URL)
                self.assertIn('no-store', response.headers['Cache-Control'])
                text = response.get_data(as_text=True)
                for leak in (SECRET, 'Demo', 'Hidden', 'sleep_score', '/private/'):
                    self.assertNotIn(leak, text)

    def test_writes_are_refused_and_cannot_mutate_data(self):
        before = self.files()
        paths = ('/', '/api/health', '/api/public/v1/me', '/api/admin/login', '/api/account/setup',
                 '/api/authorize/Demo', '/api/authorize-exchange', '/api/fetch-data', '/api/cancel-fetch/old',
                 '/api/rebuild-dashboard', '/api/create-profile', '/api/delete-profile', '/profiles/Demo/auth/tokens.json')
        for path in paths:
            for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                with self.subTest(path=path, method=method):
                    response = self.client.open(path, method=method, json={'password': 'legacy', 'clientSecret': 'replacement'})
                    self.assertEqual(response.status_code, 405)
                    self.assertEqual(response.headers['Allow'], 'GET, HEAD, OPTIONS')
                    self.assertEqual(response.json['code'], 'read_only')
        self.assertEqual(before, self.files())
        self.assertFalse(jobs.fetch_jobs)

    def test_registered_routes_are_read_only_even_with_old_admin_configuration(self):
        self.app.config.update(ADMIN_PASSWORD='old-password', SECRET_KEY='old-session-key')
        rules = {rule.rule: rule.methods for rule in self.app.url_map.iter_rules()}
        self.assertEqual(set(rules), {'/api/health', '/api/', '/api/<path:path>', '/', '/<path:path>'})
        for rule, methods in rules.items():
            self.assertLessEqual(methods, READ_ONLY, rule)
        self.assertEqual(self.client.post('/api/admin/login', json={'password': 'old-password'}).status_code, 405)

    def test_responses_set_no_cookie_or_cors_and_ignore_legacy_sessions(self):
        self.client.set_cookie('fitflare_session', 'legacy-admin-cookie')
        for path in ('/', '/mobile.html', '/api/health', '/api/public/v1/me', '/api/admin/session'):
            for method in sorted(READ_ONLY):
                with self.subTest(path=path, method=method):
                    response = self.client.open(path, method=method)
                    self.assertLess(response.status_code, 500)
                    self.assertNotIn('Set-Cookie', response.headers)
                    self.assertNotIn('Access-Control-Allow-Origin', response.headers)
                    self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
                    self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
                    self.assertEqual(response.headers['Referrer-Policy'], 'same-origin')

    def test_settings_ignore_the_retired_publication_switch(self):
        from backend.config import settings
        for mode in ('', 'public', 'private'):
            with self.subTest(mode=mode), patch.dict(os.environ, {'FITFLARE_PROFILE_ID': 'me', 'FITFLARE_DATA_ACCESS': mode}):
                self.assertEqual(settings()['OWNER_PROFILE_ID'], 'me')
                self.assertNotIn('DATA_ACCESS_MODE', settings())
                self.assertNotIn('SECRET_KEY', settings())
                self.assertEqual(create_app({**self.config, 'OWNER_PROFILE_ID': 'me'}).test_client().get('/api/health').status_code, 200)
        with self.assertRaises(ValueError):
            create_app({**self.config, 'OWNER_PROFILE_ID': '../Hidden'})
        with patch.dict(os.environ, {'FITFLARE_PROFILE_ID': 'me', 'FITBIT_PROFILE': 'Hidden'}):
            self.assertEqual(profile_paths.resolve_or_prompt_profile(), 'me')
        with self.assertRaises(ValueError):
            profile_paths.get_active_profile('../Hidden')

    def test_profile_lock_excludes_parallel_syncs(self):
        first = sync._acquire_profile_fetch_lock('Demo', 'test-1')
        self.assertIsNotNone(first)
        try:
            self.assertIsNone(sync._acquire_profile_fetch_lock('Demo', 'test-2'))
        finally:
            sync._release_profile_fetch_lock(first)
        second = sync._acquire_profile_fetch_lock('Demo', 'test-3')
        self.assertIsNotNone(second)
        sync._release_profile_fetch_lock(second)

    def test_no_scheduler_starts_on_import(self):
        self.assertIsNone(sync.auto_sync_thread)

    def test_background_sync_and_cli_discovery_only_touch_owner(self):
        for profile in ('Demo', 'Hidden'):
            (self.root / f'profiles/{profile}/auth/tokens.json').write_text(json.dumps({'refresh_token':'synthetic'}))
        self.assertEqual(profile_paths.list_profiles(), ['Demo'])
        self.assertEqual(sync._discover_syncable_profiles(), ['Demo'])
        with patch.object(sync, 'AUTO_SYNC_ENABLED', True), \
             patch.object(sync, '_profile_due_for_auto_sync', return_value=True), \
             patch.object(sync, '_run_auto_sync_for_profile') as run:
            sync.auto_sync_stop_event.clear()
            sync.run_auto_sync_cycle()
            run.assert_called_once_with('Demo')
        for operation in (sync._acquire_profile_fetch_lock, sync.run_fetch_script):
            with self.assertRaises(ValueError):
                operation('Hidden', 'untrusted-job')
        with self.assertRaises(ValueError):
            sync._run_auto_sync_for_profile('Hidden')
        self.assertFalse((self.root / 'profiles/Hidden/cache/.fetch.lock').exists())
        with patch.dict(os.environ, {'FITBIT_TOKENS_FILE': '/unrelated/tokens.json'}):
            env = sync._prepare_fetch_env('Demo')
        self.assertEqual(env['FITBIT_TOKENS_FILE'], str((self.root / 'profiles/Demo/auth/tokens.json').resolve()))
        self.assertEqual(env['FITFLARE_PROFILE_ID'], 'Demo')

    def test_background_jobs_keep_owner_isolation_without_web_controls(self):
        first, second = jobs.create_fetch('Demo'), jobs.create_fetch('Demo')
        self.assertNotEqual(first, second)
        jobs.fetch_jobs['legacy'] = dict(id='legacy', profile='Hidden', status='running')
        self.assertEqual(self.client.get('/api/health').json['active_jobs'], 0)
        self.assertEqual(self.client.get('/api/fetch-jobs').status_code, 410)
        self.assertEqual(jobs.fetch_jobs['legacy']['status'], 'running')
        with self.assertRaises(ValueError):
            jobs.create_fetch('Hidden')


if __name__ == '__main__':
    unittest.main()
