"""Background sync, file locks and progress parsing. Importing starts no threads."""
import os
import json
import subprocess
import sys
import threading
import tempfile
import fcntl
from datetime import datetime
from collections import deque
from common import panel_push
from common.profile_paths import list_profiles as list_profile_ids, owner_profile_id, profile_path_for, tokens_file_for
from .config import AUTO_SYNC_ENABLED, AUTO_SYNC_INTERVAL_SECONDS, AUTO_SYNC_SCAN_INTERVAL_SECONDS, AUTO_SYNC_STARTUP_DELAY_SECONDS
from .time_utils import _now_iso

auto_sync_thread = None
auto_sync_stop_event = threading.Event()

def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed
    except Exception:
        return None


def _auto_sync_log(message: str, level: str = "INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [AUTO-SYNC] [{level}] {message}")


def _require_owner(profile_id):
    if profile_id != owner_profile_id():
        raise ValueError('Background tasks can only use the configured personal account')
    for directory in ('auth', 'cache', 'csv'):
        profile_path_for(profile_id, directory)


def _profile_cache_dir(profile_id: str) -> str:
    _require_owner(profile_id)
    return str(profile_path_for(profile_id, 'cache'))


def _ensure_profile_cache_dir(profile_id: str):
    os.makedirs(_profile_cache_dir(profile_id), exist_ok=True)


def _profile_fetch_lock_path(profile_id: str) -> str:
    _require_owner(profile_id)
    return str(profile_path_for(profile_id, "cache", ".fetch.lock"))


def _auto_sync_state_path(profile_id: str) -> str:
    _require_owner(profile_id)
    return str(profile_path_for(profile_id, "cache", "auto_sync_state.json"))


def _dashboard_cache_path(profile_id: str) -> str:
    _require_owner(profile_id)
    return str(profile_path_for(profile_id, "cache", "dashboard.json"))


def _load_json_file(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_json_file(path: str, payload: dict):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix='.sync-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _load_auto_sync_state(profile_id: str) -> dict:
    return _load_json_file(_auto_sync_state_path(profile_id))


def _save_auto_sync_state(profile_id: str, **updates):
    state = _load_auto_sync_state(profile_id)
    state.update(updates)
    state["profile"] = profile_id
    state["updated_at"] = _now_iso()
    _write_json_file(_auto_sync_state_path(profile_id), state)


def _dashboard_generated_at(profile_id: str) -> datetime | None:
    payload = _load_json_file(_dashboard_cache_path(profile_id))
    generated_at = payload.get("generated_at")
    parsed = _parse_iso_datetime(generated_at if isinstance(generated_at, str) else None)
    if parsed:
        return parsed
    try:
        cache_path = _dashboard_cache_path(profile_id)
        if os.path.exists(cache_path):
            return datetime.fromtimestamp(os.path.getmtime(cache_path))
    except Exception:
        return None
    return None


def _last_auto_sync_reference(profile_id: str) -> datetime | None:
    state = _load_auto_sync_state(profile_id)
    candidates = [
        _parse_iso_datetime(state.get("last_attempt_at") if isinstance(state.get("last_attempt_at"), str) else None),
        _dashboard_generated_at(profile_id),
    ]
    valid = [candidate for candidate in candidates if candidate is not None]
    return max(valid) if valid else None


def _profile_has_refresh_token(profile_id: str) -> bool:
    _require_owner(profile_id)
    tokens_path = tokens_file_for(profile_id)
    payload = _load_json_file(tokens_path)
    return bool(payload.get("refresh_token"))


def _discover_syncable_profiles() -> list[str]:
    return [profile_id for profile_id in list_profile_ids() if _profile_has_refresh_token(profile_id)]


def _profile_due_for_auto_sync(profile_id: str, now_dt: datetime | None = None) -> bool:
    now_dt = now_dt or datetime.now()
    reference = _last_auto_sync_reference(profile_id)
    if reference is None:
        return True
    return (now_dt - reference).total_seconds() >= AUTO_SYNC_INTERVAL_SECONDS


def _prepare_fetch_env(profile_id: str) -> dict:
    _require_owner(profile_id)
    env = os.environ.copy()
    env["FITFLARE_PROFILE_ID"] = profile_id
    env["FITBIT_PROFILE"] = profile_id
    env["FITBIT_TOKENS_FILE"] = tokens_file_for(profile_id)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    # These child processes run while the parent owns this profile's fetch lock.
    env["FITFLARE_FETCH_LOCK_HELD"] = os.path.abspath(os.path.join("profiles", profile_id, "auth", "tokens.json"))
    return env


def _acquire_profile_fetch_lock(profile_id: str, owner: str):
    _ensure_profile_cache_dir(profile_id)
    lock_path = _profile_fetch_lock_path(profile_id)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None

    payload = {
        "profile": profile_id,
        "owner": owner,
        "pid": os.getpid(),
        "acquired_at": _now_iso(),
    }
    os.ftruncate(fd, 0)
    os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    os.fsync(fd)
    return fd


def _release_profile_fetch_lock(lock_fd):
    if lock_fd is None:
        return
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        os.close(lock_fd)
    except Exception:
        pass


def _refresh_profile_tokens(profile_id: str, log_prefix: str) -> tuple[bool, str | None]:
    _require_owner(profile_id)
    tokens_file = tokens_file_for(profile_id)
    print(f"[{log_prefix}] Checking tokens file: {tokens_file}")
    if not os.path.exists(tokens_file):
        return False, f'Profile {profile_id} not found. Run auth/authorize_google_health.py --configure --no-browser on the server'

    try:
        with open(tokens_file, "r", encoding="utf-8") as handle:
            tokens = json.load(handle)
    except Exception as exc:
        return False, f"Error checking tokens: {exc}"

    if not tokens or "refresh_token" not in tokens or not tokens.get("refresh_token"):
        return False, f'Profile {profile_id} needs authorization. Run auth/authorize_google_health.py --no-browser on the server'

    refresh_result = subprocess.run(
        [sys.executable, "auth/refresh_token.py"],
        cwd=os.getcwd(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_prepare_fetch_env(profile_id),
        timeout=30,
    )
    print(f"[{log_prefix}] Token refresh completed. Return code: {refresh_result.returncode}")

    if refresh_result.returncode == 0:
        if refresh_result.stdout:
            print(f"[{log_prefix}] {refresh_result.stdout.strip()}")
        return True, None

    error_msg = (refresh_result.stderr or refresh_result.stdout or "Token refresh failed").strip()
    if "[fitbit] Error:" in error_msg:
        error_msg = error_msg.split("[fitbit] Error:")[-1].strip()
    if "Token file not found:" in error_msg:
        error_msg = "Token file not found"
    if "Refresh token is invalid or expired" in error_msg:
        error_msg = "Refresh token is invalid or expired"
    return False, f"Token refresh failed: {error_msg}. Run auth/authorize_google_health.py --no-browser on the server"


def _run_auto_sync_for_profile(profile_id: str):
    lock_fd = _acquire_profile_fetch_lock(profile_id, "auto-sync")
    if lock_fd is None:
        _auto_sync_log(f"Skip {profile_id}: another sync is already running", "WARN")
        return

    started_at = _now_iso()
    _save_auto_sync_state(
        profile_id,
        last_attempt_at=started_at,
        last_status="running",
        last_error=None,
        last_trigger="auto",
    )
    try:
        _auto_sync_log(f"Starting scheduled sync for {profile_id}")
        ok, error_message = _refresh_profile_tokens(profile_id, f"AUTO-{profile_id}")
        if not ok:
            _save_auto_sync_state(
                profile_id,
                last_status="failed",
                last_finished_at=_now_iso(),
                last_error=error_message,
            )
            _auto_sync_log(f"{profile_id} token refresh failed: {error_message}", "ERROR")
            return

        proc = subprocess.Popen(
            [sys.executable, "fetch/fetch_all.py", "--profile", profile_id],
            cwd=os.getcwd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=0,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace",
            env=_prepare_fetch_env(profile_id),
        )
        output_lines = deque(maxlen=200)
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n")
            output_lines.append(line)
            print(f"[AUTO-{profile_id}] {line}")

        return_code = proc.wait()
        finished_at = _now_iso()
        if return_code == 0:
            _save_auto_sync_state(
                profile_id,
                last_status="completed",
                last_finished_at=finished_at,
                last_success_at=finished_at,
                last_error=None,
            )
            _auto_sync_log(f"Completed scheduled sync for {profile_id}")
            return

        error_preview = "\n".join(list(output_lines)[-20:]).strip() or f"fetch_all.py exited with code {return_code}"
        _save_auto_sync_state(
            profile_id,
            last_status="failed",
            last_finished_at=finished_at,
            last_error=error_preview,
        )
        _auto_sync_log(f"Scheduled sync failed for {profile_id} with code {return_code}", "ERROR")
    except Exception as exc:
        _save_auto_sync_state(
            profile_id,
            last_status="error",
            last_finished_at=_now_iso(),
            last_error=str(exc),
        )
        _auto_sync_log(f"Scheduled sync crashed for {profile_id}: {exc}", "ERROR")
    finally:
        _release_profile_fetch_lock(lock_fd)


def run_auto_sync_cycle():
    if not AUTO_SYNC_ENABLED:
        return

    profiles = _discover_syncable_profiles()
    if not profiles:
        _auto_sync_log("The personal account is not authorized; skipping automatic sync")
        return

    now_dt = datetime.now()
    for profile_id in profiles:
        if auto_sync_stop_event.is_set():
            return
        if not _profile_due_for_auto_sync(profile_id, now_dt):
            continue
        _run_auto_sync_for_profile(profile_id)


def _auto_sync_loop():
    if AUTO_SYNC_STARTUP_DELAY_SECONDS > 0:
        if auto_sync_stop_event.wait(AUTO_SYNC_STARTUP_DELAY_SECONDS):
            return

    while not auto_sync_stop_event.is_set():
        run_auto_sync_cycle()
        # Only does work when FITFLARE_PANEL_INGEST_TOKEN is set.
        panel_push.push_if_due(owner_profile_id())
        if auto_sync_stop_event.wait(AUTO_SYNC_SCAN_INTERVAL_SECONDS):
            return


def start_auto_sync_scheduler():
    global auto_sync_thread
    if not AUTO_SYNC_ENABLED:
        _auto_sync_log("Automatic sync disabled by FITFLARE_AUTO_SYNC_ENABLED", "WARN")
        return
    if auto_sync_thread and auto_sync_thread.is_alive():
        _auto_sync_log("Automatic sync scheduler already running")
        return

    auto_sync_stop_event.clear()
    auto_sync_thread = threading.Thread(
        target=_auto_sync_loop,
        name="fitflare-auto-sync",
        daemon=True,
    )
    auto_sync_thread.start()
    _auto_sync_log(
        f"Automatic sync scheduler started: every {AUTO_SYNC_INTERVAL_SECONDS // 3600}h, scan every {AUTO_SYNC_SCAN_INTERVAL_SECONDS}s"
    )


def stop_auto_sync_scheduler():
    auto_sync_stop_event.set()
    if auto_sync_thread and auto_sync_thread.is_alive():
        auto_sync_thread.join(timeout=5)
    _auto_sync_log("Automatic sync scheduler stopped")
