"""Read and normalize Claude Code usage files."""
import datetime as _datetime
import json
import os
import tempfile
import time


NOW_PATH = os.path.expanduser("~/.claude/usage-now.json")
HISTORY_PATH = os.path.expanduser("~/.claude/usage-history.jsonl")


def _number(value, default=0):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _integer(value, default=0):
    return int(_number(value, default))


def _text(value, default=""):
    return value if isinstance(value, str) else default


def _dict(value):
    return value if isinstance(value, dict) else {}


def _limit(value):
    value = _dict(value)
    return {
        "used_percentage": _number(value.get("used_percentage")),
        "resets_at": _number(value.get("resets_at")),
    }


def _row(value):
    value = _dict(value)
    return {
        "ts": _number(value.get("ts")),
        "five": _number(value.get("five")),
        "five_reset": _number(value.get("five_reset")),
        "week": _number(value.get("week")),
        "week_reset": _number(value.get("week_reset")),
        "ctx": _number(value.get("ctx")),
        "cost": _number(value.get("cost")),
        "model": _text(value.get("model")),
        "session": _text(value.get("session")),
    }


def _normal_now(value):
    value = _dict(value)
    model = _dict(value.get("model"))
    cost = _dict(value.get("cost"))
    context = _dict(value.get("context_window"))
    current_usage = _dict(context.get("current_usage"))
    cache = _dict(value.get("prompt_cache"))
    rate_limits = _dict(value.get("rate_limits"))
    effort = _dict(value.get("effort"))
    thinking = _dict(value.get("thinking"))
    return {
        "available": bool(value),
        "session_id": _text(value.get("session_id")),
        "session_name": _text(value.get("session_name")),
        "cwd": _text(value.get("cwd")),
        "version": _text(value.get("version")),
        "model": {
            "id": _text(model.get("id")),
            "display_name": _text(model.get("display_name"), _text(model.get("id"))),
        },
        "effort": {"level": _text(effort.get("level"))},
        "cost": {"total_cost_usd": _number(cost.get("total_cost_usd")),
                 "total_duration_ms": _number(cost.get("total_duration_ms")),
                 "total_lines_added": _integer(cost.get("total_lines_added")),
                 "total_lines_removed": _integer(cost.get("total_lines_removed"))},
        "context": {
            "total_input_tokens": _number(context.get("total_input_tokens")),
            "total_output_tokens": _number(context.get("total_output_tokens")),
            "context_window_size": _number(context.get("context_window_size")),
            "used_percentage": _number(context.get("used_percentage")),
            "remaining_percentage": _number(context.get("remaining_percentage")),
            "current_usage": {
                "input_tokens": _number(current_usage.get("input_tokens")),
                "output_tokens": _number(current_usage.get("output_tokens")),
                "cache_creation_input_tokens": _number(current_usage.get("cache_creation_input_tokens")),
                "cache_read_input_tokens": _number(current_usage.get("cache_read_input_tokens")),
            },
        },
        "exceeds_200k_tokens": bool(value.get("exceeds_200k_tokens", False)),
        "cache": {
            "warm": bool(cache.get("warm", False)),
            "hit_ratio": _number(cache.get("hit_ratio")),
            "requests": _integer(cache.get("requests")),
            "misses": _integer(cache.get("misses")),
            "ttl": _text(cache.get("ttl")),
            "expires_at": _number(cache.get("expires_at")),
            "recache_tokens_if_cold": _number(cache.get("recache_tokens_if_cold")),
            "last_miss_at": cache.get("last_miss_at"),
            "last_miss_cause": _text(cache.get("last_miss_cause")),
        },
        "fast_mode": bool(value.get("fast_mode", False)),
        "thinking": bool(thinking.get("enabled", False)),
        "rate_limits": {
            "five_hour": _limit(rate_limits.get("five_hour")),
            "seven_day": _limit(rate_limits.get("seven_day")),
        },
    }


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read().strip()
        return json.loads(text) if text else {}
    except (OSError, ValueError, TypeError):
        return {}


def _read_history(path):
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            rows.append(_row(value))
    return rows


def _prune_history(path):
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return
    if len(lines) <= 40000:
        return
    directory = os.path.dirname(path) or "."
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory,
                                        prefix=".usage-history.", delete=False) as handle:
            temp_path = handle.name
            handle.writelines(lines[-20000:])
        os.replace(temp_path, path)
    except OSError:
        try:
            os.unlink(temp_path)
        except (OSError, UnboundLocalError):
            pass


def _today_cost(rows, now_ts):
    today = _datetime.datetime.fromtimestamp(now_ts).date()
    maxima = {}
    for row in rows:
        if not row["ts"] or _datetime.datetime.fromtimestamp(row["ts"]).date() != today:
            continue
        session = row["session"]
        if not session:
            continue
        maxima[session] = max(maxima.get(session, 0.0), row["cost"])
    return sum(maxima.values())


def from_payload(payload, history, now_ts=None, mtime=None):
    """Build the render-facing structure without touching the filesystem."""
    now_ts = time.time() if now_ts is None else float(now_ts)
    rows = [_row(row) for row in history if isinstance(row, dict)]
    current = _normal_now(payload)
    # The live payload is newer than the last sample, so without folding it in
    # "today" reads lower than "this session" for up to one sampling interval.
    live = [{"ts": now_ts, "session": current["session_id"],
             "cost": current["cost"]["total_cost_usd"]}] if current["session_id"] else []
    return {
        **current,
        "history": rows,
        "today_cost": _today_cost(rows + live, now_ts),
        "now_ts": now_ts,
        "mtime": mtime,
        "stale": mtime is not None and now_ts - mtime > 120,
    }


def load(now_path=NOW_PATH, history_path=HISTORY_PATH, now_ts=None):
    now_ts = time.time() if now_ts is None else float(now_ts)
    try:
        mtime = os.path.getmtime(now_path)
    except OSError:
        mtime = None
    _prune_history(history_path)
    return from_payload(_read_json(now_path), _read_history(history_path), now_ts, mtime)
