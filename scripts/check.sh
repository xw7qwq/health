#!/usr/bin/env bash
# Full release gate. It uses synthetic profiles only and never touches production.
set -euo pipefail
cd "$(dirname "$0")/.."
root=$PWD
image=${CHECK_IMAGE:-fitflare:check}
results=${TEST_OUTPUT_DIR:-$root/test-results}
mkdir -p "$results"
results=$(cd "$results" && pwd)
# A failed run must not leave a previous success receipt behind.
rm -f "$results/release-gate.json" "$results/validated-image.txt"
runtime=$(mktemp -d)
container="fitflare-check-$$"
cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; rm -rf "$runtime"; }
trap cleanup EXIT
python3 scripts/audit.py
python3 scripts/audit_history.py
python3 -m unittest tests.test_history_audit -v
git diff --check
for file in scripts/*.sh; do bash -n "$file"; done
revision=$(git rev-parse HEAD)
source_dirty=false
[[ -z "$(git status --porcelain)" ]] || source_dirty=true
docker build -f "${CHECK_DOCKERFILE:-Dockerfile}" \
  --label "org.opencontainers.image.source=https://github.com/xw7qwq/fitflare" \
  --label "org.opencontainers.image.revision=$revision" \
  --label "dev.fitflare.source-dirty=$source_dirty" \
  -t "$image" . > "$results/build.log" 2>&1
run=(docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp --user 10001:10001 -e PYTHONDONTWRITEBYTECODE=1 -e FITFLARE_AUTO_SYNC_ENABLED=false -e FITFLARE_PROFILE_ID=Demo)
"${run[@]}" --entrypoint python "$image" scripts/audit.py --image
"${run[@]}" -v "$root/tests:/app/tests:ro" --entrypoint python "$image" -m unittest discover -s tests -p 'test_*.py' -v 2>&1 | tee "$results/backend-tests.log"
python3 tests/fixture.py "$runtime/profiles"
# These are generated synthetic fixtures, not production health/authorization files.
chmod -R a+rX "$runtime"
start_preview() {
  docker run -d --name "$container" --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp --user 10001:10001 \
    -p 127.0.0.1::9000 -v "$runtime/profiles:/app/profiles:ro" \
    -e PYTHONDONTWRITEBYTECODE=1 -e FITFLARE_AUTO_SYNC_ENABLED=false \
    -e FITFLARE_PROFILE_ID=Demo "$image" >/dev/null
  port=$(docker port "$container" 9000/tcp | sed 's/.*://')
  export BASE_URL="http://127.0.0.1:$port"
  for attempt in $(seq 1 40); do
    if curl -fsS "$BASE_URL/api/health" >/dev/null 2>&1; then return; fi
    sleep 1
  done
  docker logs --tail 30 "$container"
  return 1
}
expect() {
  local got
  got=$(curl -sS -o /dev/null -w '%{http_code} %{redirect_url}' "${@:2}")
  [[ "$got" == "$1" ]] || { echo "Expected '$1' from ${*:2}, got '$got'" >&2; return 1; }
}
start_preview
# The running image answers only its health check: pages and files go to the panel, the old API is gone, writes are refused.
curl -fsS "$BASE_URL/api/health" | python3 -c 'import json, sys; assert json.load(sys.stdin)["status"] == "healthy"'
for path in / /mobile.html /app.js /server.py /profiles/Demo/auth/tokens.json /profiles/Demo/cache/dashboard.json; do
  expect '301 https://lucius7.dev/health/' "$BASE_URL$path"
done
expect '410 ' "$BASE_URL/api/public/v1/me/dashboard"
expect '405 ' -X POST "$BASE_URL/api/fetch-data"
validated=$(docker image inspect "$image" --format '{{.Id}}')
printf '%s\n' "$validated" > "$results/validated-image.txt"
python3 - "$results/release-gate.json" "$revision" "$source_dirty" "$image" "$validated" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
path, revision, source_dirty, image, image_id = sys.argv[1:]
receipt = dict(status='passed', completed_at=datetime.now(timezone.utc).isoformat(), fixture='synthetic',
               revision=revision, source_dirty=source_dirty == 'true', image=image, image_id=image_id)
Path(path).write_text(json.dumps(receipt, indent=2) + '\n')
PY
printf 'Release checks passed. Validated image: %s\n' "$image"
