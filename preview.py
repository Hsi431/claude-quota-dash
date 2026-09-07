#!/usr/bin/env python3
import json
import math
import os
import sys
import time

from PIL import Image

import data
import render


def _payload(danger, now, week_reset, five_reset):
    context_tokens = 260000 if danger else 55100
    return {
        "session_id": "preview-session",
        "session_name": "ESP32 C3外設狀態動畫說明",
        "effort": {"level": "high"},
        "model": {"id": "claude-opus-5[1m]", "display_name": "Opus 5 (1M context)"},
        "version": "2.1.260",
        "cost": {"total_cost_usd": 3.78 if danger else 1.395, "total_duration_ms": 2820000,
                 "total_lines_added": 12, "total_lines_removed": 3},
        "context_window": {"total_input_tokens": context_tokens, "total_output_tokens": 160,
                            "context_window_size": 1000000,
                            "current_usage": {"input_tokens": context_tokens, "output_tokens": 160},
                            "used_percentage": context_tokens / 10000,
                            "remaining_percentage": 100 - context_tokens / 10000},
        "exceeds_200k_tokens": danger,
        "prompt_cache": {"warm": not danger, "hit_ratio": 0.42 if danger else 0.92,
                          "requests": 23 if danger else 7, "misses": 8 if danger else 0,
                          "ttl": "1h", "expires_at": now + 3600,
                          "recache_tokens_if_cold": context_tokens,
                          "last_miss_at": now - 1800 if danger else None,
                          "last_miss_cause": "context_refresh" if danger else None},
        "fast_mode": danger,
        "thinking": {"enabled": True},
        "rate_limits": {"five_hour": {"used_percentage": 92 if danger else 40, "resets_at": five_reset},
                         "seven_day": {"used_percentage": 92 if danger else 40, "resets_at": week_reset}},
    }


def _history(danger, now, week_reset, five_reset):
    week_start = week_reset - 7 * 86400
    five_start = five_reset - 5 * 3600
    rows = []
    count = 168
    for index in range(count + 1):
        ts = week_start + index * 3600
        if ts > now:
            break
        fraction = (ts - week_start) / max(1, now - week_start)
        target = 92 if danger else 40
        week = max(0, min(100, target * fraction + math.sin(index * 1.7) * (1.2 if danger else 0.8)))
        five_fraction = max(0, min(1, (ts - five_start) / max(1, now - five_start)))
        five_target = 92 if danger else 40
        five = max(0, min(100, five_target * five_fraction + math.sin(index * 1.3) * 0.7))
        rows.append({"ts": ts, "five": five, "five_reset": five_reset, "week": week,
                     "week_reset": week_reset, "ctx": 26 if danger else 6,
                     "cost": (3.78 if danger else 1.395) * fraction,
                     "model": "claude-opus-5[1m]", "session": "preview-session"})
    return rows


def scenario(danger, now):
    week_reset = now + (2 * 86400 if danger else 3 * 86400)
    five_reset = now + (42 * 60 if danger else 2 * 3600 + 11 * 60)
    history = _history(danger, now, week_reset, five_reset)
    payload = _payload(danger, now, week_reset, five_reset)
    return data.from_payload(payload, history, now, now)


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    now = int(time.time())
    outputs = []
    for name, danger in (("healthy", False), ("danger", True)):
        dashboard = scenario(danger, now)
        for index, page in enumerate((render.page_quota, render.page_five, render.page_context, render.page_cache), 1):
            path = os.path.join(out_dir, f"{name}_page{index}.png")
            page(dashboard).save(path)
            outputs.append(path)
    if os.path.exists(data.NOW_PATH):
        path = os.path.join(out_dir, "real_page1.png")
        render.page_quota(data.load()).save(path)
        outputs.append(path)
    for path in outputs:
        with Image.open(path) as image:
            assert image.size == (320, 170), path
        assert os.path.getsize(path) > 0, path
    print("\n".join(outputs))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: preview.py OUT_DIR")
    main(sys.argv[1])
