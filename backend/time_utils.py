from datetime import datetime


def _now_iso() -> str:
    return datetime.now().isoformat()
