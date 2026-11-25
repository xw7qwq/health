"""Daily, weekly and monthly series built from the dashboard cache, for the panel snapshot."""
from __future__ import annotations

from typing import Any

from common.dashboard_cache import load_dataset_rows


SERIES_DIMENSIONS = {
    "daily": "date",
    "weekly": "period",
    "monthly": "period",
}

FALLBACK_METRIC_META = {
    "sleep_score": {"label": "睡眠得分", "unit": "分", "tone": "blue"},
    "sleep_hours": {"label": "睡眠时长", "unit": "小时", "tone": "amber"},
    "steps": {"label": "步数", "unit": "步", "tone": "green"},
    "active_minutes": {"label": "活跃分钟", "unit": "分钟", "tone": "teal"},
    "active_zone_minutes": {"label": "燃脂区分钟", "unit": "分钟", "tone": "red"},
    "hrv": {"label": "HRV", "unit": "ms", "tone": "blue"},
    "deep_rmssd": {"label": "深睡 RMSSD", "unit": "ms", "tone": "teal"},
    "rhr": {"label": "静息心率", "unit": "bpm", "tone": "red"},
    "calories_out": {"label": "消耗热量", "unit": "kcal", "tone": "amber"},
    "sedentary_minutes": {"label": "久坐分钟", "unit": "分钟", "tone": "amber"},
    "activity_calories": {"label": "活动热量", "unit": "kcal", "tone": "amber"},
    "lightly_active_minutes": {"label": "轻度活跃分钟", "unit": "分钟", "tone": "green"},
    "fairly_active_minutes": {"label": "中等活跃分钟", "unit": "分钟", "tone": "green"},
    "very_active_minutes": {"label": "高强度活跃分钟", "unit": "分钟", "tone": "red"},
    "minutes_asleep": {"label": "入睡分钟", "unit": "分钟", "tone": "blue"},
    "minutes_awake": {"label": "清醒分钟", "unit": "分钟", "tone": "amber"},
    "time_in_bed": {"label": "在床分钟", "unit": "分钟", "tone": "blue"},
    "efficiency": {"label": "睡眠效率", "unit": "%", "tone": "green"},
    "minutes_deep": {"label": "深睡分钟", "unit": "分钟", "tone": "teal"},
    "minutes_rem": {"label": "REM 分钟", "unit": "分钟", "tone": "blue"},
    "minutes_light": {"label": "浅睡分钟", "unit": "分钟", "tone": "amber"},
    "minutes_wake_stages": {"label": "醒着分钟", "unit": "分钟", "tone": "red"},
    "minutes_to_fall_asleep": {"label": "入睡耗时", "unit": "分钟", "tone": "amber"},
    "minutes_after_wakeup": {"label": "醒后停留", "unit": "分钟", "tone": "amber"},
    "nap_count": {"label": "小睡次数", "unit": "次", "tone": "teal"},
    "deep_pct": {"label": "深睡占比", "unit": "%", "tone": "teal"},
    "rem_pct": {"label": "REM 占比", "unit": "%", "tone": "blue"},
    "days": {"label": "覆盖天数", "unit": "天", "tone": "teal"},
}


def metric_meta_map(dashboard: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for item in dashboard.get("stats") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        mapping[key] = {
            "key": key,
            "label": item.get("label") or key,
            "unit": item.get("unit"),
            "tone": item.get("tone") or FALLBACK_METRIC_META.get(key, {}).get("tone") or "blue",
        }
    for key, value in FALLBACK_METRIC_META.items():
        if key not in mapping:
            mapping[key] = {
                "key": key,
                "label": value.get("label") or key,
                "unit": value.get("unit"),
                "tone": value.get("tone") or "blue",
            }
    return mapping


def metric_descriptor(key: str, dashboard: dict[str, Any]) -> dict[str, Any]:
    mapping = metric_meta_map(dashboard)
    if key in mapping:
        return mapping[key]
    return {
        "key": key,
        "label": key.replace("_", " "),
        "unit": None,
        "tone": "blue",
    }


def available_series_metrics(rows: list[dict[str, Any]], dimension: str) -> list[str]:
    keys: set[str] = set()
    for row in rows:
        for key, value in row.items():
            if key == dimension or value is None or isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                keys.add(key)
    return sorted(keys)


def normalize_metric_keys(
    requested: str | None,
    available: list[str],
    default: list[str] | None = None,
) -> list[str]:
    if not requested:
        return list(default or available)
    requested_keys = [part.strip() for part in requested.split(",") if part.strip()]
    selected = [key for key in requested_keys if key in available]
    return selected or list(default or available)


def build_series_payload(
    profile_id: str,
    dashboard: dict[str, Any],
    granularity: str,
    metrics: str | None = None,
    limit: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    key = str(granularity or "").strip().lower()
    if key not in SERIES_DIMENSIONS:
        raise KeyError(key)
    rows = load_dataset_rows(profile_id, key)
    dimension = SERIES_DIMENSIONS[key]
    available = available_series_metrics(rows, dimension)
    selected = normalize_metric_keys(metrics, available)
    if limit is not None:
        rows = rows[-limit:]
    points = [{dimension: row.get(dimension), **{metric: row.get(metric) for metric in selected}} for row in rows]
    descriptors = [metric_descriptor(metric, dashboard) for metric in selected]
    return {
        "granularity": key,
        "dimension": dimension,
        "metrics": descriptors,
        "points": points,
    }, {
        "count": len(points),
        "available_metrics": available,
    }
