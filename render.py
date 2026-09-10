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
    #  The crab's claws, one step down from its shell, so a claw held out in
    #  front reads as being in front rather than merging into the outline.
    "ACCENT_SHADE": "#C24A1E",
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

#  Chinese needs more pixels than Latin at the same nominal size -- 11px labels
#  come out as a blot on a 1.9" panel -- so the label and body sizes grow, and
#  the three label-over-value stacks become single rows to pay for the height.
CJK_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
CJK_INDEX = 3                    # Noto Sans CJK TC
CJK_SIZES = {"hero": 44, "big": 24, "value": 15, "body": 14, "label": 16}
#  Latin anchors measure from the ascender, which leaves a Chinese glyph sitting
#  low enough to touch whatever is under it; the ink box is the honest top here.
CJK_ANCHORS = {None: "lt", "ra": "rt"}
_CJK_FONTS = {}


def _cjk(name):
    if name not in _CJK_FONTS:
        try:
            _CJK_FONTS[name] = ImageFont.truetype(CJK_FONT, CJK_SIZES[name], index=CJK_INDEX)
        except OSError:
            raise SystemExit(f"{CJK_FONT} is missing -- install Noto Sans CJK "
                             "(Debian/Ubuntu: apt install fonts-noto-cjk)")
    return _CJK_FONTS[name]


LANG_FILE = os.path.expanduser("~/.config/quota-dash/lang")
LANGUAGES = ("en", "zh")


def language():
    try:
        with open(LANG_FILE) as handle:
            code = handle.read().strip()
    except OSError:
        return "en"
    return code if code in LANGUAGES else "en"


def set_language(code):
    os.makedirs(os.path.dirname(LANG_FILE), exist_ok=True)
    with open(LANG_FILE, "w") as handle:
        handle.write(code)


#  Read once per frame in _base rather than per string: the file is the source
#  of truth, but a page must not change language halfway down.
_ACTIVE = "en"

STRINGS = {
    "quota": ("QUOTA", "額度"),
    "five_hour": ("5 HOUR", "五小時"),
    "seven_day": ("7 DAY", "七天"),
    "context": ("CONTEXT", "上下文"),
    "cache": ("CACHE", "快取"),
    "stale": ("STALE {}", "過期 {}"),
    "no_data": ("NO DATA", "無資料"),
    "at": ("AT {}", "{} 重置"),
    "in": ("IN {}", "剩 {}"),
    "until_reset": ("UNTIL RESET", "距離重置"),
    "hits_cap": ("HITS CAP {}", "{} 用完"),
    "wont_hit_cap": ("WON'T HIT CAP", "不會用完"),
    "used_left": ("{}% USED · {}% LEFT", "已用 {}% · 剩 {}%"),
    "context_used": ("CONTEXT USED", "已用上下文"),
    "model": ("MODEL", "模型"),
    "thinking": ("THINKING", "思考"),
    "fast": ("FAST", "快速"),
    "cache_hit": ("CACHE HIT", "快取命中"),
    "requests": ("{} REQ · {} MISS", "{} 次請求 · {} 次未中"),
    "recache": ("REBUILD IF IT GOES COLD", "冷掉要重建"),
    "tokens": ("{} TOK", "{} tok"),
    "last_miss": ("LAST MISS", "上次未命中"),
    "act_idle": ("IDLE", "待機"),
    "act_run": ("RUNNING", "跑指令"),
    "act_write": ("WRITING", "寫東西"),
    "act_look": ("READING", "讀檔"),
    "act_wave": ("WAITING", "等你"),
    "act_cheer": ("DONE", "完成"),
    "act_stuck": ("STUCK", "卡住"),
    "act_sleep": ("ASLEEP", "睡了"),
    "none": ("NONE", "無"),
    "session_cost": ("${} SESSION", "本次 ${}"),
    "today_cost": ("${} TODAY · {}M", "今日 ${} · {}M"),
}


def _t(key, *args):
    return STRINGS[key][LANGUAGES.index(_ACTIVE)].format(*args)


def _cjk_text(value):
    return _ACTIVE != "en" and any(ord(char) > 0x2E80 for char in value)

_CRAB = crab.Crab()

#  The crab is a redrawn nod to Anthropic's Clawd, so it is off unless asked
#  for: `quota crab on` (or `touch` this file) puts it on the first page in
#  place of the plain column, and the choice survives a restart.
CRAB_FLAG = os.path.expanduser("~/.config/quota-dash/crab")

#  Two things the crab can be given on top of its posture, each remembered the
#  same way: a prop for the activity it is in (`quota props on`) and a word for
#  that activity under the box (`quota label on`). Both off by default -- the
#  point of the crab is that you read it without reading anything.
PROPS_FLAG = os.path.expanduser("~/.config/quota-dash/props")

#  (main, secondary) colour for each activity's prop. Props are not the crab, so
#  they are painted in the panel's own greys and greens rather than its orange --
#  a white keyboard under an orange crab, not an orange keyboard.
PROP_COLOURS = {
    "write": ("TEXT", "TEXT_FAINT"),      # bright keys on a dim desk
    "run": ("TEXT_DIM", "TEXT_DIM"),
    "look": ("COOL", "TEXT_FAINT"),
    "wave": ("TEXT", "TEXT_DIM"),
    "cheer": ("TEXT", "TEXT_DIM"),
    "stuck": ("COOL", "TEXT_DIM"),        # cool rain out of a grey cloud
    "sleep": ("TEXT_DIM", "TEXT_DIM"),
}
LABEL_FLAG = os.path.expanduser("~/.config/quota-dash/label")


#  What Claude Code is doing right now, set by hooks (`quota pose run`). It is
#  the second layer over the crab's quota posture, and it lapses on its own so a
#  session that dies mid-command does not leave the crab scuttling forever.
_ACTIVITY = crab.DEFAULT_ACTIVITY
_ACTIVITY_UNTIL = 0.0
ACTIVITY_LAPSE = 90.0


def set_activity(name, hold=None):
    """-> True if the name is one the crab knows. `hold` keeps it for that many
    seconds instead of the usual lapse, for poses no hook will ever refresh."""
    global _ACTIVITY, _ACTIVITY_UNTIL
    if name not in crab.ACTIVITIES:
        return False
    _ACTIVITY = name
    _ACTIVITY_UNTIL = time.monotonic() + (hold or ACTIVITY_LAPSE)
    return True


def activity():
    if _ACTIVITY != crab.DEFAULT_ACTIVITY and time.monotonic() >= _ACTIVITY_UNTIL:
        return crab.DEFAULT_ACTIVITY
    return _ACTIVITY


def crab_enabled():
    return os.path.exists(CRAB_FLAG)


def _set_flag(path, on):
    if on:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "a").close()
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def set_crab(on):
    _set_flag(CRAB_FLAG, on)


def props_enabled():
    return os.path.exists(PROPS_FLAG)


def set_props(on):
    _set_flag(PROPS_FLAG, on)


def label_enabled():
    return os.path.exists(LABEL_FLAG)


def set_label(on):
    _set_flag(LABEL_FLAG, on)


def _crisp(image):
    draw = ImageDraw.Draw(image)
    draw.fontmode = "1"
    return draw


def _text(draw, xy, value, size, color, anchor=None):
    value = str(value)
    if _cjk_text(value):
        # Small Chinese needs the soft edge that small Latin has to do without.
        draw.fontmode = "L"
        draw.text(xy, value, font=_cjk(size), fill=color,
                  anchor=CJK_ANCHORS.get(anchor, anchor))
        return
    draw.fontmode = "L" if size in SMOOTH else "1"
    draw.text(xy, value, font=_font(size), fill=color, anchor=anchor)


def _text_width(value, size):
    value = str(value)
    font = _cjk(size) if _cjk_text(value) else _font(size)
    return ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(value, font=font)


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
    global _ACTIVE
    _ACTIVE = language()
    image = Image.new("RGB", (W, H), COLORS["BG"])
    draw = _crisp(image)
    top = 3 if _ACTIVE != "en" else 5
    _text(draw, (8, top), _t(title), "label", COLORS["TEXT_DIM"])
    if page in (3, 4) and d.get("cwd"):
        _text(draw, (78, top), _fit(os.path.basename(d["cwd"]).upper(), "label", 130), "label",
              COLORS["TEXT_FAINT"])
    if d.get("stale"):
        _text(draw, (283, top), _t("stale", _duration(d["now_ts"] - d.get("mtime", d["now_ts"]),
              compact=True)), "label", COLORS["ALARM"], anchor="ra")
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
        _text(draw, ((left + right) // 2, (top + bottom) // 2 - 6), _t("no_data"), "label", COLORS["TEXT_FAINT"], anchor="mm")
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


def _pair(draw, x, y, label, value, label_colour, value_colour):
    """A label and its value: stacked in English, side by side in Chinese,
    where 16px glyphs leave no room for a second row."""
    if _ACTIVE == "en":
        _text(draw, (x, y), label, "label", label_colour)
        _text(draw, (x, y + 12), value, "value", value_colour)
        return
    _text(draw, (x, y + 8), label, "label", label_colour)
    _text(draw, (x + _text_width(label, "label") + 10, y + 9), value, "value", value_colour)


def _quota_block(image, draw, top, label, pct, reset, now, window, colour):
    """One quota: its label, the number that matters, and when it clears."""
    _text(draw, (8, top if _ACTIVE == "en" else top - 3), label, "label", COLORS["TEXT_DIM"])
    _text(draw, (8, top + 48), f"{pct}%", "hero", colour, anchor="ls")
    weekday = window > 24 * 3600
    _text(draw, (100, top + 18), _ts_text(reset, weekday=weekday), "value", COLORS["TEXT"])
    _text(draw, (100, top + 38), _t("in", _duration(reset - now, compact=True)) if reset else "--",
          "label", COLORS["TEXT_FAINT"])


def page_quota(d):
    image, draw = _base(d, 1, "quota")
    now = d.get("now_ts", 0)
    for top, name, window in ((30, "seven_day", 7 * 86400), (102, "five_hour", 5 * 3600)):
        limit = _limit(d, name)
        reset = limit.get("resets_at", 0)
        pct = _pct(limit.get("used_percentage"))
        label = _t("seven_day" if window > 24 * 3600 else "five_hour")
        _quota_block(image, draw, top, label, pct, reset, now, window, _level(pct))
    draw.line((8, 92, 205, 92), fill=COLORS["HAIRLINE"])
    draw.line((214, 28, 214, 160), fill=COLORS["HAIRLINE"])

    week = _pct(_limit(d, "seven_day").get("used_percentage"))
    if crab_enabled():
        # The crab carries the seven-day number in its posture, which is the
        # one thing the digits next to it cannot do.
        # The box is wider than the crab so the activity layer has room to
        # sway it without clipping a claw against the edge.
        act = activity()
        layers = _CRAB.frame(time.monotonic(), week, 5, 96, 140, act, props_enabled())
        prop_colour, dim_colour = PROP_COLOURS.get(act, ("TEXT", "TEXT_FAINT"))
        for name, colour in (("body", "ACCENT"), ("shade", "ACCENT_SHADE"),
                             ("prop_dim", dim_colour), ("prop", prop_colour)):
            mask = layers.get(name)
            if mask is None or not mask.any():
                continue
            image.paste(Image.new("RGB", (96, 140), COLORS[colour]), (219, 24),
                        Image.fromarray(mask).convert("1"))
        if label_enabled():
            _text(draw, (267, 146), _t("act_" + act), "label", COLORS["TEXT_DIM"], anchor="mt")
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
    image, draw = _base(d, 2, "five_hour")
    limit = _limit(d, "five_hour")
    now, reset = d.get("now_ts", 0), limit.get("resets_at", 0)
    used = _pct(limit.get("used_percentage"))
    # A colon makes a duration read as a clock time, next to a real clock time.
    # Units remove the ambiguity: "4H 49M" can only be a countdown.
    left = max(0, int(reset - now))
    hours, minutes = left // 3600, (left % 3600) // 60
    countdown = f"{hours}H {minutes:02d}M" if hours else f"{minutes}M"
    _text(draw, (8, 62), countdown, "hero", COLORS["TEXT"], anchor="ls")
    _text(draw, (190, 36), _t("until_reset"), "label", COLORS["TEXT_DIM"])
    _text(draw, (190, 50), _t("at", _ts_text(reset)), "value", COLORS["TEXT_FAINT"])

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
        right, color = _t("hits_cap", _ts_text(hit)), COLORS["ALARM"]
    else:
        right, color = _t("wont_hit_cap"), COLORS["TEXT_DIM"]
    # The bottom strip is 14px tall; a Chinese glyph needs all of it.
    strip = 156 if _ACTIVE == "en" else 153
    _text(draw, (8, strip), _t("used_left", used, 100 - used), "body", COLORS["TEXT_DIM"])
    _text(draw, (312, strip), right, "body", color, anchor="ra")
    return image


def _tokens(value):
    value = float(value or 0)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1000:
        return f"{value / 1000:.1f}K"
    return str(int(value))


def page_context(d):
    image, draw = _base(d, 3, "context")
    context = d.get("context", {})
    size = context.get("context_window_size", 0) or 1
    tokens = context.get("total_input_tokens", 0) + context.get("total_output_tokens", 0)
    pct = _pct(context.get("used_percentage"))

    _text(draw, (8, 28), _t("context_used"), "label", COLORS["TEXT_DIM"])
    _text(draw, (8, 74), f"{pct}%", "big", _level(pct), anchor="ls")
    _text(draw, (312, 56), f"{_tokens(tokens)} / {_tokens(size)}", "value",
          COLORS["TEXT"], anchor="ra")

    draw.rectangle((8, 88, 312, 102), fill=COLORS["SURFACE"])
    draw.rectangle((8, 88, 8 + 304 * min(1, tokens / size), 102), fill=COLORS["ACCENT"])
    tick = 8 + min(304, 304 * 200000 / size)
    draw.line((tick, 85, tick, 105),
              fill=COLORS["ALARM"] if d.get("exceeds_200k_tokens") else COLORS["TEXT_DIM"])
    _text(draw, (tick, 108), "200K", "label", COLORS["TEXT_FAINT"], anchor="ma")

    name = d.get("model", {}).get("display_name", _t("no_data"))
    name, _, qualifier = name.partition(" (")
    label = _t("model")
    room = 200 if _ACTIVE == "en" else 200 - int(_text_width(label, "label")) - 10
    _pair(draw, 8, 120, label, _fit(name, "value", room), COLORS["TEXT_DIM"], COLORS["TEXT"])
    if qualifier:
        _text(draw, (312, 133), qualifier.rstrip(")").upper(), "label", COLORS["TEXT_FAINT"],
              anchor="ra")

    draw.line((8, 150, 311, 150), fill=COLORS["HAIRLINE"])
    modes = [(_t("thinking"), d.get("thinking")),
             (d.get("effort", {}).get("level", "").upper(), bool(d.get("effort", {}).get("level"))),
             (_t("fast"), d.get("fast_mode"))]
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
    image, draw = _base(d, 4, "cache")
    cache = d.get("cache", {})
    ratio = cache.get("hit_ratio", 0) or 0
    hit = _pct(ratio * 100 if ratio <= 1 else ratio)

    _text(draw, (8, 28), _t("cache_hit"), "label", COLORS["TEXT_DIM"])
    _text(draw, (8, 74), f"{hit}%", "big",
          COLORS["COOL"] if hit >= 80 else COLORS["ACCENT"], anchor="ls")
    _text(draw, (312, 56), _t("requests", cache.get("requests", 0), cache.get("misses", 0)),
          "value", COLORS["TEXT"], anchor="ra")

    _pair(draw, 8, 88, _t("recache"), _t("tokens", _tokens(cache.get("recache_tokens_if_cold"))),
          COLORS["TEXT_DIM"], COLORS["TEXT"])
    _text(draw, (312, 101), f"TTL {cache.get('ttl', '').upper() or '--'}", "label",
          COLORS["TEXT_FAINT"], anchor="ra")

    label = _t("last_miss")
    miss = cache.get("last_miss_cause")
    room = 300 if _ACTIVE == "en" else 300 - int(_text_width(label, "label")) - 10
    if miss:
        at = cache.get("last_miss_at")
        ago = f" · {_duration(d.get('now_ts', 0) - at, compact=True)} AGO" if at else ""
        _pair(draw, 8, 120, label, _fit(f"{miss}{ago}".upper(), "value", room),
              COLORS["TEXT_DIM"], COLORS["TEXT"])
    else:
        _pair(draw, 8, 120, label, _t("none"), COLORS["TEXT_DIM"], COLORS["TEXT_FAINT"])

    cost = d.get("cost", {})
    draw.line((8, 150, 311, 150), fill=COLORS["HAIRLINE"])
    _text(draw, (8, 154), _t("session_cost", f"{cost.get('total_cost_usd', 0):.2f}"), "body",
          COLORS["TEXT_DIM"])
    _text(draw, (312, 154), _t("today_cost", f"{d.get('today_cost', 0):.2f}",
          int(round(cost.get("total_duration_ms", 0) / 60000))), "body",
          COLORS["TEXT_DIM"], anchor="ra")
    return image
