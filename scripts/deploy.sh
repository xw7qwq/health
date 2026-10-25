#!/usr/bin/env bash
# Check -> validate runtime -> deploy -> verify -> automatic image rollback on failure.
set -euo pipefail
cd "$(dirname "$0")/.."
exec 9>"$(git rev-parse --git-common-dir)/deploy.lock"
flock -n 9 || { echo 'Another deployment is in progress.'; exit 1; }
# Only deploy a reviewed main commit, with no local source edits.
git fetch --prune origin main
assert_release_source() {
  [[ "$(git symbolic-ref --quiet --short HEAD)" == main ]] &&
  [[ -z "$(git status --porcelain)" ]] &&
  [[ "$(git rev-parse HEAD)" == "$(git rev-parse refs/remotes/origin/main)" ]] || {
    echo 'Deploy from a clean main checkout matching origin/main.' >&2
    return 1
  }
}
assert_release_source
revision=$(git rev-parse HEAD)
image="fitflare:release-$(date -u +%Y%m%dT%H%M%SZ)"
# A host may build on a locally patched base; the gate then validates that exact image.
if [[ -z "${CHECK_DOCKERFILE:-}" && -f Dockerfile.host ]]; then export CHECK_DOCKERFILE=Dockerfile.host; fi
CHECK_IMAGE="$image" bash scripts/check.sh
assert_release_source
[[ "$revision" == "$(git rev-parse HEAD)" ]]
validated=$(cat "${TEST_OUTPUT_DIR:-test-results}/validated-image.txt")
[[ "$validated" == "$(docker image inspect "$image" --format '{{.Id}}')" ]]
[[ "$revision" == "$(docker image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" ]]
[[ false == "$(docker image inspect "$image" --format '{{index .Config.Labels "dev.fitflare.source-dirty"}}')" ]]
# Refuse to interrupt a sync that currently holds a profile lock.
docker exec -i fitflare-app python - <<'PY'
import fcntl
from pathlib import Path
for path in Path('/app/profiles').glob('*/cache/.fetch.lock'):
    with path.open('r+') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Active health data sync; retry deployment after it completes.')
PY
runtime=$(docker compose config --format json)
printf '%s' "$runtime" | python3 -c 'import json,sys; c=json.load(sys.stdin)["services"]["fitflare"]; assert c["user"].split(":")[0] not in ("0","root"), "Configure a non-root FITFLARE_UID first"; assert c.get("read_only")'
unset runtime
old=$(docker inspect fitflare-app --format '{{.Image}}')
docker tag "$old" fitflare:rollback
rollback() {
  echo 'Deployment validation failed; restoring the preceding image.' >&2
  FITFLARE_IMAGE="$old" docker compose up -d --no-deps --no-build fitflare
  docker tag "$old" fitflare:latest
}
trap rollback ERR
FITFLARE_IMAGE="$image" docker compose up -d --no-deps --no-build fitflare
for attempt in $(seq 1 45); do
  health=$(docker inspect fitflare-app --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}')
  [[ "$health" == healthy ]] && break
  sleep 1
done
[[ "$health" == healthy ]]
# The new container serves only its health check; pages and files redirect to the panel and the old API is gone.
docker exec -i fitflare-app python - <<'PY'
import json
import urllib.request
from urllib.error import HTTPError
base = 'http://127.0.0.1:9000'
class KeepRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None
opener = urllib.request.build_opener(KeepRedirects)
def fetch(path, data=None):
    request = urllib.request.Request(base + path, data=data, headers={'Content-Type': 'application/json'} if data else {})
    try:
        with opener.open(request, timeout=10) as response:
            return response.status, response.headers.get('Location'), response.read()
    except HTTPError as error:
        return error.code, error.headers.get('Location'), error.read()
status, _, body = fetch('/api/health')
assert status == 200 and json.loads(body)['status'] == 'healthy'
for path in ('/', '/mobile.html', '/profiles/index.json'):
    if fetch(path)[:2] != (301, 'https://lucius7.dev/health/'):
        raise SystemExit('Unexpected response for a retired page or private file: ' + path)
for path in ('/api/dashboard', '/api/public/v1/me', '/api/admin/session'):
    status, _, body = fetch(path)
    if status != 410 or json.loads(body).get('code') != 'gone':
        raise SystemExit('Unexpected response for a retired API route: ' + path)
if fetch('/api/fetch-data', data=b'{}')[0] != 405:
    raise SystemExit('HTTP write boundary failed')
print('Production redirect and response checks passed.')
PY
# Keep the existing compose default pointing to the successfully validated build.
docker tag "$image" fitflare:latest
python3 - "${TEST_OUTPUT_DIR:-test-results}" "$revision" "$validated" "$old" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
directory = Path(sys.argv[1])
receipt = json.loads((directory / 'release-gate.json').read_text())
assert receipt['revision'] == sys.argv[2] and receipt['image_id'] == sys.argv[3]
assert receipt['status'] == 'passed' and receipt['source_dirty'] is False
receipt.update(status='deployed', deployed_at=datetime.now(timezone.utc).isoformat(), previous_image_id=sys.argv[4])
(directory / 'deployment.json').write_text(json.dumps(receipt, indent=2) + '\n')
PY
trap - ERR
printf 'Deployed %s at %s; rollback image preserved at fitflare:rollback\n' "$image" "$revision"
