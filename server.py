#!/usr/bin/env python3
"""Fitflare application factory: the health check, and redirects for the retired website; imports start no jobs."""
import os
from flask import Flask, jsonify, redirect
from backend.config import settings, AUTO_SYNC_ENABLED, AUTO_SYNC_INTERVAL_SECONDS, AUTO_SYNC_SCAN_INTERVAL_SECONDS
from backend.security import install_security
from backend.sync import start_auto_sync_scheduler, stop_auto_sync_scheduler
from backend import jobs
from backend.time_utils import _now_iso
from common.profile_paths import owner_profile_id

# The website and its public API moved to the lucius7.dev panel, which receives snapshots from common/panel_push.py.
PANEL_HEALTH_URL = 'https://lucius7.dev/health/'
PANEL_API_URL = 'https://lucius7.dev/about/'


def create_app(config=None):
    app = Flask(__name__, static_folder=None)
    app.config.update(settings())
    app.config.update(config or {})
    install_security(app)

    @app.get('/api/health')
    def health_check():
        with jobs.lock:
            active = sum(job.get('status') == 'running' and job.get('profile') == owner_profile_id() for job in jobs.fetch_jobs.values())
        return jsonify(status='healthy', timestamp=_now_iso(), active_jobs=active,
                       auto_sync_enabled=AUTO_SYNC_ENABLED,
                       auto_sync_interval_seconds=AUTO_SYNC_INTERVAL_SECONDS,
                       auto_sync_scan_interval_seconds=AUTO_SYNC_SCAN_INTERVAL_SECONDS)

    @app.get('/api/', defaults={'path': ''})
    @app.get('/api/<path:path>')
    def retired_api(path):
        return jsonify(error='This API has been retired; the data is on the lucius7.dev panel.', code='gone', see=PANEL_API_URL), 410

    # Old pages, bookmarks and file paths all land on the panel's health page; no file is ever served.
    @app.get('/', defaults={'path': ''})
    @app.get('/<path:path>')
    def moved(path):
        return redirect(PANEL_HEALTH_URL, 301)

    @app.errorhandler(500)
    def internal_error(error):
        return 'Internal server error', 500

    return app


app = create_app()

if __name__ == '__main__':
    start_auto_sync_scheduler()
    try:
        app.run(host='0.0.0.0', port=int(os.getenv('PORT', '9000')), debug=False)
    finally:
        stop_auto_sync_scheduler()
