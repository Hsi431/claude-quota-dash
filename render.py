"""Pure Pillow renderers for the three dashboard pages."""
import datetime
import math
import os
import time

from PIL import Image, ImageDraw, ImageFont

import crab


W, H = 320, 170
COLORS = {
    "BG": "#0A0A0B", "SURFACE": "#14151A", "HAIRLINE": "#262931",
    "GRID": "#1F2229", "TEXT": "#EDEAE6", "TEXT_DIM": "#8B8880",
    "TEXT_FAINT": "#55534F", "ACCENT": "#EA5C27", "COOL": "#6E9E8C",
    "ALARM": "#C4162E",
}
FONT_DIR = "/usr/share/fonts/truetype/jetbrains-mono"


def _load(file_name, size):
    #  Pillow's own error here is "cannot open resource", which says nothing
    #  about which font is missing or how to get it.
    try:
        return ImageFont.truetype(f"{FONT_DIR}/{file_name}", size)
    except OSError:
        raise SystemExit(f"{FONT_DIR}/{file_name} is missing -- install JetBrains Mono "
                         "(Debian/Ubuntu: apt install fonts-jetbrains-mono)")


FONTS = {
    "hero": _load("JetBrainsMono-Bold.ttf", 44),
    "big": _load("JetBrainsMono-Bold.ttf", 24),
    "value": _load("JetBrainsMono-Medium.ttf", 15),
    "body": _load("JetBrainsMono-Medium.ttf", 12),
    "label": _load("JetBrainsMono-Medium.ttf", 11),
}


def _font(name):
    return FONTS[name]


SMOOTH = {"hero", "big"}         # sizes with enough pixels to carry a soft edge

_CRAB = crab.Crab()

#  The crab is a redrawn nod to Anthropic's Clawd, so it is off unless asked
#  for: `quota crab on` (or `touch` this file) puts it on the first page in
#  place of the plain column, and the choice survives a restart.
CRAB_FLAG = os.path.expanduser("~/.config/quota-dash/crab")


def crab_enabled():
    return os.path.exists(CRAB_FLAG)


def set_crab(on):
    if on:
        os.makedirs(os.path.dirname(CRAB_FLAG), exist_ok=True)
        open(CRAB_FLAG, "a").close()
        return
    try:
        os.unlink(CRAB_FLAG)
    except FileNotFoundError:
        pass


def _crisp(image):
    draw = ImageDraw.Draw(image)
    draw.fontmode = "1"
    return draw


def _text(draw, xy, value, size, color, anchor=None):
    draw.fontmode = "L" if size in SMOOTH else "1"
    draw.text(xy, str(value), font=_font(size), fill=color, anchor=anchor)


def _text_width(value, size):
    return ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(str(value), font=_font(size))


def _fit(value, size, max_width):
    value = str(value)
    if _text_width(value, size) <= max_width:
        return value
    while value and _text_width(value + "…", size) > max_width:
        value = value[:-1]
    return value + "…"


def _pct(value):
    return max(0, min(100, int(round(float(value or 0)))))


def _level(pct):
    """Colour by how full a quota is, not by whether it is ahead of an even
    burn. Pace flickers: it flips at a line nobody can see, and on a five-hour
    window that refills by itself it means nothing anyway."""
    if pct >= 91:
        return COLORS["ALARM"]
    if pct >= 61:
        return COLORS["ACCENT"]
    return COLORS["TEXT"]


def _limit(d, name):
    return d.get("rate_limits", {}).get(name, {})


def _ts_text(ts, weekday=False):
    if not ts:
        return "--:--"
    dt = datetime.datetime.fromtimestamp(ts)
    return f"{dt.strftime('%a ').upper() if weekday else ''}{dt:%H:%M}"


def _duration(seconds, compact=False):
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if compact:
        if days:
            return f"{days}D {hours}H"
        if hours:
            return f"{hours}H{minutes:02d}M"
        return f"{minutes}M"
    if hours + days * 24:
        return f"{hours + days * 24}:{minutes:02d}"
    return f"{minutes}M"


def _base(d, page, title):
    image = Image.new("RGB", (W, H), COLORS["BG"])
    draw = _crisp(image)
    _text(draw, (8, 5), title, "label", COLORS["TEXT_DIM"])
    if page in (3, 4) and d.get("cwd"):
        _text(draw, (78, 5), _fit(os.path.basename(d["cwd"]).upper(), "label", 130), "label",
              COLORS["TEXT_FAINT"])
    if d.get("stale"):
        _text(draw, (283, 5), "STALE " + _duration(d["now_ts"] - d.get("mtime", d["now_ts"]),
              compact=True), "label", COLORS["ALARM"], anchor="ra")
    for index, x in enumerate((289, 296, 303, 310), 1):
        draw.ellipse((x - 2, 8, x + 2, 12), fill=COLORS["ACCENT"] if index == page else COLORS["TEXT_FAINT"])
    draw.line((0, 21, 319, 21), fill=COLORS["HAIRLINE"])
    return image, draw


def _dashed(draw, points, fill, width=1, dash=4, gap=3):
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        length = math.hypot(x2 - x1, y2 - y1)
        if not length:
            continue
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        pos = 0.0
        while pos < length:
            end = min(pos + dash, length)
            draw.line((x1 + ux * pos, y1 + uy * pos, x1 + ux * end, y1 + uy * end),
                      fill=fill, width=width)
            pos += dash + gap


def _curve_points(d, key, start, end):
    now = d.get("now_ts", 0)
    rows = []
    for row in d.get("history", []):
        ts = row.get("ts", 0)
        if start <= ts <= min(end, now) and row.get(key) is not None:
            rows.append((float(ts), float(row.get(key, 0))))
    current = _limit(d, "seven_day" if key == "week" else "five_hour")
    if d.get("available") and start <= now <= end:
        rows.append((now, float(current.get("used_percentage", 0))))
    rows.sort()
    unique = []
    for point in rows:
        if unique and point[0] == unique[-1][0]:
            unique[-1] = point
        else:
            unique.append(point)
    return unique


def _plot_y(value, top, bottom):
    return bottom - max(0, min(100, value)) * (bottom - top) / 100


def _draw_curve(image, d, key, start, end, box, grid_values, predict=False):
    left, top, right, bottom = box
    draw = _crisp(image)
    for value in grid_values:
        y = _plot_y(value, top, bottom)
        draw.line((left, y, right, y), fill=COLORS["GRID"])
    if end <= start:
        return None, None
    draw.line((left, top, left, bottom), fill=COLORS["GRID"])
    xscale = (right - left) / (end - start)
    ref = lambda ts: 100 * (ts - start) / (end - start)
    _dashed(draw, [(left, bottom), (right, top)], COLORS["TEXT_FAINT"])
    points = _curve_points(d, key, start, end)
    mapped = [(left + (ts - start) * xscale, _plot_y(value, top, bottom), ts, value)
              for ts, value in points]
    if not mapped:
        _text(draw, ((left + right) // 2, (top + bottom) // 2 - 6), "NO DATA", "label", COLORS["TEXT_FAINT"], anchor="mm")
        return None, None

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    fill = ImageDraw.Draw(overlay)
    for first, second in zip(mapped, mapped[1:]):
        x1, y1, ts1, value1 = first
        x2, y2, ts2, value2 = second
        ref1, ref2 = _plot_y(ref(ts1), top, bottom), _plot_y(ref(ts2), top, bottom)
        sign1, sign2 = value1 - ref(ts1), value2 - ref(ts2)
        if sign1 * sign2 < 0:
            ratio = abs(sign1) / (abs(sign1) + abs(sign2))
            cross_x = x1 + (x2 - x1) * ratio
            cross_y = y1 + (y2 - y1) * ratio
            polygons = [((x1, y1), (cross_x, cross_y), (cross_x, ref1 + (ref2 - ref1) * ratio), (x1, ref1)),
                        ((cross_x, cross_y), (x2, y2), (x2, ref2), (cross_x, ref1 + (ref2 - ref1) * ratio))]
            for polygon, positive in zip(polygons, (sign1 > 0, sign2 > 0)):
                fill.polygon(polygon, fill=(217, 119, 87, 38) if positive else (110, 158, 140, 31))
        else:
            fill.polygon(((x1, y1), (x2, y2), (x2, ref2), (x1, ref1)),
                         fill=(217, 119, 87, 38) if sign1 >= 0 else (110, 158, 140, 31))
    image.paste(overlay, (0, 0), overlay)
    draw = _crisp(image)
    draw.line([(p[0], p[1]) for p in mapped], fill=COLORS["ACCENT"], width=2 if key == "week" else 1)
    last = mapped[-1]
    draw.ellipse((last[0] - 3, last[1] - 3, last[0] + 3, last[1] + 3), fill=COLORS["ACCENT"])

    hit = None
    predicted = None
    if predict:
        recent = [point for point in mapped if point[2] >= d.get("now_ts", 0) - 6 * 3600]
        if len(recent) >= 2 and recent[-1][2] > recent[0][2]:
            rate = (recent[-1][3] - recent[0][3]) / ((recent[-1][2] - recent[0][2]) / 3600)
            now = d.get("now_ts", 0)
            current_value = recent[-1][3]
            if rate > 0:
                hit = now + max(0, (100 - current_value) / rate * 3600)
            target_ts = min(end, hit) if hit is not None else end
            target_value = min(100, current_value + max(0, rate) * (target_ts - now) / 3600)
            target_x = left + (target_ts - start) * xscale
            target_y = _plot_y(target_value, top, bottom)
            _dashed(draw, [(last[0], last[1]), (target_x, target_y)], COLORS["ACCENT"])
            predicted = current_value + max(0, rate) * (end - now) / 3600
            if hit is not None and hit <= end:
                hit_x = left + (hit - start) * xscale
                draw.line((hit_x, top, hit_x, bottom), fill=COLORS["ALARM"])
    return hit, predicted


def _quota_block(image, draw, top, label, pct, reset, now, window, colour):
    """One quota: its label, the number that matters, and when it clears."""
    _text(draw, (8, top), label, "label", COLORS["TEXT_DIM"])
    _text(draw, (8, top + 48), f"{pct}%", "hero", colour, anchor="ls")
    weekday = window > 24 * 3600
    _text(draw, (100, top + 18), _ts_text(reset, weekday=weekday), "value", COLORS["TEXT"])
    _text(draw, (100, top + 38), f"IN {_duration(reset - now, compact=True)}" if reset else "--",
          "label", COLORS["TEXT_FAINT"])


def page_quota(d):
    image, draw = _base(d, 1, "QUOTA")
    now = d.get("now_ts", 0)
    for top, name, window in ((30, "seven_day", 7 * 86400), (102, "five_hour", 5 * 3600)):
        limit = _limit(d, name)
        reset = limit.get("resets_at", 0)
        pct = _pct(limit.get("used_percentage"))
        label = "7 DAY" if window > 24 * 3600 else "5 HOUR"
        _quota_block(image, draw, top, label, pct, reset, now, window, _level(pct))
    draw.line((8, 92, 205, 92), fill=COLORS["HAIRLINE"])
    draw.line((214, 28, 214, 160), fill=COLORS["HAIRLINE"])

    week = _pct(_limit(d, "seven_day").get("used_percentage"))
    if crab_enabled():
        # The crab carries the seven-day number in its posture, which is the
        # one thing the digits next to it cannot do.
        fb = _CRAB.frame(time.monotonic(), week, 5, 90, 140)
        tint = Image.new("RGB", (90, 140), COLORS["ACCENT"])
        image.paste(tint, (222, 24), Image.fromarray(fb).convert("1"))
    else:
        _week_column(draw, week)
    return image


def _week_column(draw, pct):
    """The week as a column of segments, for when the crab is not drawn."""
    lit = int(round(pct / 10.0))
    colour = _level(pct)
    for index in range(10):
        bottom = 156 - index * 13
        draw.rectangle((248, bottom - 9, 286, bottom),
                       fill=colour if index < lit else COLORS["GRID"])


def page_five(d):
    image, draw = _base(d, 2, "5 HOUR")
    limit = _limit(d, "five_hour")
    now, reset = d.get("now_ts", 0), limit.get("resets_at", 0)
    used = _pct(limit.get("used_percentage"))
    # A colon makes a duration read as a clock time, next to a real clock time.
    # Units remove the ambiguity: "4H 49M" can only be a countdown.
    left = max(0, int(reset - now))
    hours, minutes = left // 3600, (left % 3600) // 60
    countdown = f"{hours}H {minutes:02d}M" if hours else f"{minutes}M"
    _text(draw, (8, 62), countdown, "hero", COLORS["TEXT"], anchor="ls")
    _text(draw, (190, 36), "UNTIL RESET", "label", COLORS["TEXT_DIM"])
    _text(draw, (190, 50), f"AT {_ts_text(reset)}", "value", COLORS["TEXT_FAINT"])

    fill_color = _level(used) if used >= 61 else COLORS["ACCENT"]
    # The percentage sits above the bar, not on it: inside the bar its colour has
    # to flip exactly where the fill edge passes under the glyphs.
    _text(draw, (312, 76), f"{used}%", "value", fill_color, anchor="rs")
    draw.rounded_rectangle((8, 80, 312, 100), radius=2, fill=COLORS["SURFACE"])
    if used:
        draw.rounded_rectangle((8, 80, 8 + 304 * used / 100, 100), radius=2, fill=fill_color)

    start = reset - 5 * 3600 if reset else now - 5 * 3600
    hit, _ = _draw_curve(image, d, "five", start, reset or now, (8, 108, 312, 146), (0, 50, 100), predict=True)
    draw.line((8, 150, 311, 150), fill=COLORS["HAIRLINE"])
    if hit is not None and hit <= (reset or now):
        right, color = f"HITS CAP {_ts_text(hit)}", COLORS["ALARM"]
    else:
        right, color = "WON'T HIT CAP", COLORS["TEXT_DIM"]
    _text(draw, (8, 156), f"{used}% USED · {100 - used}% LEFT", "body", COLORS["TEXT_DIM"])
    _text(draw, (312, 156), right, "body", color, anchor="ra")
    return image


def _tokens(value):
    value = float(value or 0)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1000:
        return f"{value / 1000:.1f}K"
    return str(int(value))


def page_context(d):
    image, draw = _base(d, 3, "CONTEXT")
    context = d.get("context", {})
    size = context.get("context_window_size", 0) or 1
    tokens = context.get("total_input_tokens", 0) + context.get("total_output_tokens", 0)
    pct = _pct(context.get("used_percentage"))

    _text(draw, (8, 28), "CONTEXT USED", "label", COLORS["TEXT_DIM"])
    _text(draw, (8, 74), f"{pct}%", "big", _level(pct), anchor="ls")
    _text(draw, (312, 56), f"{_tokens(tokens)} / {_tokens(size)}", "value",
          COLORS["TEXT"], anchor="ra")

    draw.rectangle((8, 88, 312, 102), fill=COLORS["SURFACE"])
    draw.rectangle((8, 88, 8 + 304 * min(1, tokens / size), 102), fill=COLORS["ACCENT"])
    tick = 8 + min(304, 304 * 200000 / size)
    draw.line((tick, 85, tick, 105),
              fill=COLORS["ALARM"] if d.get("exceeds_200k_tokens") else COLORS["TEXT_DIM"])
    _text(draw, (tick, 108), "200K", "label", COLORS["TEXT_FAINT"], anchor="ma")

    name = d.get("model", {}).get("display_name", "NO DATA")
    name, _, qualifier = name.partition(" (")
    _text(draw, (8, 120), "MODEL", "label", COLORS["TEXT_DIM"])
    _text(draw, (8, 132), _fit(name, "value", 200), "value", COLORS["TEXT"])
    if qualifier:
        _text(draw, (312, 133), qualifier.rstrip(")").upper(), "label", COLORS["TEXT_FAINT"],
              anchor="ra")

    draw.line((8, 150, 311, 150), fill=COLORS["HAIRLINE"])
    modes = [("THINKING", d.get("thinking")),
             (d.get("effort", {}).get("level", "").upper(), bool(d.get("effort", {}).get("level"))),
             ("FAST", d.get("fast_mode"))]
    chips = [m for m in modes if m[0]]
    cursor = 8
    for index, (label, enabled) in enumerate(chips):
        _text(draw, (cursor, 154), label, "body",
              COLORS["TEXT"] if enabled else COLORS["TEXT_FAINT"])
        cursor += int(_text_width(label, "body")) + 14
        if index < len(chips) - 1:
            _text(draw, (cursor - 10, 154), "·", "body", COLORS["TEXT_FAINT"])
    return image


def page_cache(d):
    image, draw = _base(d, 4, "CACHE")
    cache = d.get("cache", {})
    ratio = cache.get("hit_ratio", 0) or 0
    hit = _pct(ratio * 100 if ratio <= 1 else ratio)

    _text(draw, (8, 28), "CACHE HIT", "label", COLORS["TEXT_DIM"])
    _text(draw, (8, 74), f"{hit}%", "big",
          COLORS["COOL"] if hit >= 80 else COLORS["ACCENT"], anchor="ls")
    _text(draw, (312, 56), f"{cache.get('requests', 0)} REQ · {cache.get('misses', 0)} MISS",
          "value", COLORS["TEXT"], anchor="ra")

    _text(draw, (8, 88), "REBUILD IF IT GOES COLD", "label", COLORS["TEXT_DIM"])
    _text(draw, (8, 100), f"{_tokens(cache.get('recache_tokens_if_cold'))} TOK", "value",
          COLORS["TEXT"])
    _text(draw, (312, 101), f"TTL {cache.get('ttl', '').upper() or '--'}", "label",
          COLORS["TEXT_FAINT"], anchor="ra")

    _text(draw, (8, 120), "LAST MISS", "label", COLORS["TEXT_DIM"])
    miss = cache.get("last_miss_cause")
    if miss:
        at = cache.get("last_miss_at")
        ago = f" · {_duration(d.get('now_ts', 0) - at, compact=True)} AGO" if at else ""
        _text(draw, (8, 132), _fit(f"{miss}{ago}".upper(), "value", 300), "value", COLORS["TEXT"])
    else:
        _text(draw, (8, 132), "NONE", "value", COLORS["TEXT_FAINT"])

    cost = d.get("cost", {})
    draw.line((8, 150, 311, 150), fill=COLORS["HAIRLINE"])
    _text(draw, (8, 154), f"${cost.get('total_cost_usd', 0):.2f} SESSION", "body",
          COLORS["TEXT_DIM"])
    _text(draw, (312, 154), f"${d.get('today_cost', 0):.2f} TODAY · "
          f"{int(round(cost.get('total_duration_ms', 0) / 60000))}M", "body",
          COLORS["TEXT_DIM"], anchor="ra")
    return image
