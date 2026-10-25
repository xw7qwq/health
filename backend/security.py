"""Read-only HTTP boundary: a health check and redirects only; account operations are CLI-only."""
from flask import jsonify, request
from common.profile_paths import validate_profile_id


def install_security(app):
    validate_profile_id(app.config['OWNER_PROFILE_ID'])
    app.before_request(guard_request)
    app.after_request(response_headers)


def guard_request():
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        return jsonify(error='This service is read-only', code='read_only'), 405, {'Allow': 'GET, HEAD, OPTIONS'}


def response_headers(response):
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Frame-Options'] = 'DENY'
    return response
