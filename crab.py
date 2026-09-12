"""A crab of my own, drawn for this screen.

Two layers move it. Its posture follows the seven-day quota: upright and
breathing slowly while there is room, sagging as the week burns down, flat on
the sand when it is nearly gone. Over that sits whatever Claude Code is doing
right now -- running a command, writing, reading, waiting on you -- which moves
the arms, the eyes and the tempo but never the height. That split is deliberate:
the height is the one thing the digits beside it cannot show, so activity is not
allowed to overwrite it.

The pixels are mine, drawn for this screen, but the character is a nod to
Anthropic's Clawd -- which is why the dashboard leaves it off until asked
(`quota crab on`).
"""
import functools
import math
import random

import numpy as np

#  Only the left half is drawn; the right half is its mirror, so the crab cannot
#  come out lopsided. '#' lit, '.' dark, 'o' eye (a hole in the shell, filled in
#  when blinking). Eleven columns a side, eighteen rows.
#  Geometry taken by measuring Claude Code's own crab: a 17x11 grid, body 13
#  wide by 9 tall, arms poking exactly two columns out of each side across three
#  rows, eyes one column wide and two tall, four thin legs. Earlier passes were
#  drawn from memory and came out as a beetle, then as a flattened version of
#  this; the numbers below are measured, not recalled.
W = 17
H = 18                           # headroom above and below for arms and legs
BODY_COLS = (2, 14)
ARM_COLS = (0, 16)
EYE_COLS = (4, 12)
LEG_COLS = (4, 6, 10, 12)
ARM_ROWS = 3
LEG_ROWS = 2

#  The arms ride up and down inside the body's own rows, exactly as the real one
#  does; what changes with the week is how tall the body still stands.
#  `breath` is (seconds, screen pixels) -- the travel is in final screen pixels,
#  not grid cells, so it has to be large to read at all on a 140px-tall box.
POSTURES = {
    "tall":  dict(top=3, body=9, arm=2, eyes=2, splay=False, breath=(3.2, 8)),
    "mid":   dict(top=4, body=9, arm=4, eyes=2, splay=False, breath=(3.8, 7)),
    "tired": dict(top=5, body=8, arm=5, eyes=1, splay=True,  breath=(4.8, 5)),
    "spent": dict(top=7, body=7, arm=4, eyes=1, splay=True,  breath=(6.5, 3)),
}

#  The second layer. `arms` names how the two claws move, `reach` how far in
#  grid rows, `swing` the seconds per cycle, `bob`/`sway` scale the body's own
#  motion, `kick` swings the legs. Names are plain English on purpose: this
#  crab shares nothing with the one on the round device.
ACTIVITIES = {
    "idle":  dict(swing=None, arms="still", reach=0, eyes="idle",    bob=1.0, sway=0, kick=0),
    "run":   dict(swing=0.40, arms="pump",  reach=3, eyes="forward", bob=1.9, sway=3, kick=1),
    "write": dict(swing=0.50, arms="tap",   reach=6, eyes="down",    bob=0.5, sway=0, kick=0),
    "look":  dict(swing=2.60, arms="still", reach=0, eyes="scan",    bob=1.0, sway=3, kick=0),
    "wave":  dict(swing=0.46, arms="wave",  reach=4, eyes="forward", bob=1.2, sway=1, kick=0),
    "cheer": dict(swing=0.36, arms="raise", reach=5, eyes="wide",    bob=2.6, sway=2, kick=1),
    "stuck": dict(swing=3.00, arms="droop", reach=5, eyes="down",    bob=0.5, sway=0, kick=0),
    "sleep": dict(swing=6.00, arms="droop", reach=2, eyes="shut",    bob=0.7, sway=0, kick=0),
}
DEFAULT_ACTIVITY = "idle"

#  Switching activity used to cut from one sine straight into another, and the
#  switch is the one moment anybody looks up. The limbs slide across instead.
#  The dashboard animates this page at 8 Hz, so a duration that is not a whole
#  number of 125 ms frames is a duration that never happens. 0.12 s of wind-up
#  was the first guess and it was worth exactly one frame.
SETTLE = 0.375                   # three frames
RELEASE = 0.125                  # one: a wound-up claw is let go, not eased

#  Before a claw commits it moves the other way first, or the action reads as a
#  jump cut. Seconds of wind-up, and the row offset to hold during it (positive
#  is down). The shell takes no part in this: its height is the seven-day
#  number, so a crouch is not available and the whole tell lives in the claws.
ANTICIPATE = {"cheer": (0.25, 2), "stuck": (0.375, -1)}


@functools.lru_cache(maxsize=None)
def _grid(name, arm_l=0, arm_r=0, eye_dy=0, kick=0, shut=False):
    spec = POSTURES[name]
    g = [["." for _ in range(W)] for _ in range(H)]

    def fill(y, x0, x1, mark="#"):
        if 0 <= y < H:
            for x in range(max(0, x0), min(W - 1, x1) + 1):
                g[y][x] = mark

    top = spec["top"]
    for i in range(spec["body"]):
        fill(top + i, *BODY_COLS)
    #  Each claw rides on its own row offset, so the crab can pump, wave or
    #  droop.
    base = top + spec["arm"]
    #  A claw held away from the shell needs a limb behind it, or it reads as a
    #  brick floating alongside; the limb is the inner column, drawn from the
    #  shell out to wherever the claw has got to. It is laid down first so the
    #  claw's own shading survives on top of it.
    for offset, col in ((arm_l, BODY_COLS[0] - 1), (arm_r, BODY_COLS[1] + 1)):
        if offset:
            for y in range(min(base, base + offset),
                           max(base, base + offset) + ARM_ROWS):
                fill(y, col, col)
    #  Shading is one row, on the edge where the claw meets what is behind it:
    #  the underside of a raised claw, the top of a hanging one. That single
    #  darker row is what separates two shapes of the same colour. A claw shaded
    #  end to end just looks like a claw painted a different colour.
    for i in range(ARM_ROWS):
        seam = ARM_ROWS - 1 if i == ARM_ROWS - 1 else 0
        mark_l = "c" if (arm_l < 0 and i == seam) or (arm_l > 0 and i == 0) else "#"
        mark_r = "c" if (arm_r < 0 and i == seam) or (arm_r > 0 and i == 0) else "#"
        fill(base + i + arm_l, ARM_COLS[0], BODY_COLS[0] - 1, mark_l)
        fill(base + i + arm_r, BODY_COLS[1] + 1, ARM_COLS[1], mark_r)
    for i in range(LEG_ROWS):
        y = top + spec["body"] + i
        for index, col in enumerate(LEG_COLS):
            drift = 0
            if spec["splay"] and col in (LEG_COLS[0], LEG_COLS[-1]):
                drift = -i if col == LEG_COLS[0] else i
            if kick:                     # outer legs out, inner legs in, then back
                drift += kick if index < 2 else -kick
            fill(y, col + drift, col + drift)
    if shut:
        #  Asleep: the eyes are two closed lines, not two missing holes.
        y = top + 2 + eye_dy + spec["eyes"] - 1
        if 0 <= y < H:
            for col in EYE_COLS:
                for x in (col - 1, col):
                    g[y][x] = "o"
    else:
        for i in range(spec["eyes"]):
            y = top + 2 + i + eye_dy
            if 0 <= y < H:
                for col in EYE_COLS:
                    g[y][col] = "o"
    return tuple("".join(row) for row in g)


ORDER = ("tall", "mid", "tired", "spent")

BOB = {name: spec["breath"] for name, spec in POSTURES.items()}
BLINK_EVERY = {"tall": (3.0, 8.0), "mid": (3.0, 8.0), "tired": (2.0, 5.0), "spent": (1.5, 4.0)}
BLINK_FOR = {"tall": 0.20, "mid": 0.20, "tired": 0.45, "spent": 0.9}


def posture_for(pct):
    """Bands line up with the number's colour, so the crab lies down on the same
    step where the digits turn red."""
    if pct < 61:
        return "tall"
    if pct < 81:
        return "mid"
    if pct < 91:
        return "tired"
    return "spent"


def _arms(kind, reach, phase):
    """-> (left, right) row offsets. Negative lifts the claw above the shell."""
    if not reach or kind == "still":
        return 0, 0
    swing = math.sin(phase)
    if kind == "pump":                   # scuttling: the claws alternate
        return int(round(reach * swing)), int(round(-reach * swing))
    if kind == "tap":                    # typing: the claws beat down in turn
        return (int(round(reach * abs(swing))),
                int(round(reach * abs(math.cos(phase)))))
    if kind == "wave":                   # one claw held up and waving
        return 0, -reach + int(round(1.5 * swing))
    if kind == "raise":                  # both claws up, bouncing
        lift = -reach + int(round(swing))
        return lift, lift
    if kind == "droop":                  # hanging, with just enough sway to live
        sag = reach + int(round(0.6 * swing))
        return sag, sag
    return 0, 0


def sprite(rows, blink=False, glance=0):
    """-> (shell, claws) bool arrays. The claws come back on their own layer so
    they can be painted darker and read as being in front of the shell. Eyes
    stay holes in the shell; glance shifts them by -1/0/+1 column."""
    h, w = len(rows), len(rows[0])
    body = np.zeros((h, w), bool)
    claws = np.zeros((h, w), bool)
    eyes = np.zeros((h, w), bool)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == "#":
                body[y, x] = True
            elif ch == "c":
                claws[y, x] = True
            elif ch == "o":
                body[y, x] = True
                eyes[y, x] = True
    if not blink:
        if glance:
            eyes = np.roll(eyes, glance, axis=1)
        body &= ~eyes
    return body, claws


def _place(spr, scale, w, h, dy, dx):
    """Blow a grid up by `scale` and drop it into a w x h frame, offset by dy/dx."""
    big = np.kron(spr, np.ones((scale, scale), bool))
    fb = np.zeros((h, w), bool)
    y = (h - big.shape[0]) // 2 + dy
    x = (w - big.shape[1]) // 2 + dx
    ys, xs = max(0, y), max(0, x)
    big = big[ys - y:h - y, xs - x:w - x]
    fb[ys:ys + big.shape[0], xs:xs + big.shape[1]] = big
    return fb


#  Props. Each activity may put one small object in the empty band above or
#  below the crab -- a keyboard to type on, a cloud to be stuck under. They sit
#  at a fixed height rather than riding the crab's own bob, so the keyboard
#  stays on the desk while the claws come down onto it.

def _fill(layer, x0, y0, x1, y1):
    h, w = layer.shape
    if x1 < 0 or y1 < 0 or x0 >= w or y0 >= h:
        return
    layer[max(0, y0):min(h, y1 + 1), max(0, x0):min(w, x1 + 1)] = True


def _outline(layer, x0, y0, x1, y1):
    _fill(layer, x0, y0, x1, y0)
    _fill(layer, x0, y1, x1, y1)
    _fill(layer, x0, y0, x0, y1)
    _fill(layer, x1, y0, x1, y1)


def _keyboard(prop, dim, phase, w, h):
    keys, key_w, gap = 7, 6, 2
    span = keys * key_w + (keys - 1) * gap
    x0, y = (w - span) // 2, 98
    _fill(dim, x0 - 4, y + 10, x0 + span + 3, y + 12)         # the desk it sits on
    struck = int(phase / math.pi * 2) % keys                  # one key down at a time
    for i in range(keys):
        drop = 3 if i == struck else 0
        left = x0 + i * (key_w + gap)
        _fill(prop, left, y + drop, left + key_w - 1, y + 6 + drop)


def _dust(prop, dim, phase, w, h):
    #  Sand streaking backwards under a scuttling crab.
    drift = phase / (2 * math.pi)
    for index, (length, y) in enumerate(((14, 98), (10, 106), (16, 114))):
        travel = (drift + index / 3.0) % 1.0
        x = int(w - 6 - travel * (w - 12)) - length
        _fill(dim, x, y, x + length, y + 2)


def _scan(prop, dim, phase, w, h):
    #  A bar sweeping the width of the box, in step with the eyes below it.
    span = 30
    x = int((w - span) / 2 + math.sin(phase) * (w - span) / 2.0)
    _fill(prop, x, 9, x + span, 12)
    _fill(dim, x + 3, 14, x + 7, 18)                          # end ticks, like a ruler
    _fill(dim, x + span - 7, 14, x + span - 3, 18)


def _bubble(prop, dim, phase, w, h):
    #  Waiting on you: a speech bubble with the dots still coming.
    x0, y0, x1, y1 = w - 40, 4, w - 8, 24
    _outline(prop, x0, y0, x1, y1)
    _fill(prop, x0 + 6, y1 + 1, x0 + 11, y1 + 4)              # the tail
    lit = int(phase / (2 * math.pi) * 4) % 4
    for i in range(3):
        if i < lit:
            _fill(prop, x0 + 7 + i * 8, y0 + 9, x0 + 10 + i * 8, y0 + 12)


def _sparks(prop, dim, phase, w, h):
    for index, (cx, cy, r) in enumerate(((15, 21, 8), (w // 2, 9, 10), (w - 15, 23, 8))):
        if math.sin(phase + index * 2.1) <= 0:                # they go off in turn
            continue
        _fill(prop, cx - r, cy - 1, cx + r, cy + 1)
        _fill(prop, cx - 1, cy - r, cx + 1, cy + r)
        for step in range(1, r // 2 + 1):                     # stubby diagonals
            for dx, dy in ((step, step), (step, -step), (-step, step), (-step, -step)):
                _fill(prop, cx + dx, cy + dy, cx + dx, cy + dy)


def _cloud(prop, dim, phase, w, h):
    cx = w // 2
    _fill(dim, cx - 18, 8, cx + 18, 16)
    _fill(dim, cx - 12, 2, cx + 8, 8)
    for index, offset in enumerate((-11, 0, 11)):             # rain, falling in turn
        fall = int(((phase / (2 * math.pi) + index / 3.0) % 1.0) * 12)
        _fill(prop, cx + offset, 18 + fall, cx + offset + 1, 21 + fall)


def _zs(prop, dim, phase, w, h):
    #  Three Z's drifting up and off the top of the box.
    for index in range(3):
        rise = ((phase / (2 * math.pi) + index / 3.0) % 1.0)
        size = 3 + index
        y = int(30 - rise * 30)
        x = w - 34 + index * 9
        if y < -size * 2:
            continue
        _fill(prop, x, y, x + size * 2, y + 1)                # top bar
        _fill(prop, x, y + size * 2, x + size * 2, y + size * 2 + 1)
        for step in range(size * 2):                          # the diagonal
            _fill(prop, x + size * 2 - step, y + step, x + size * 2 - step + 1, y + step)


PROPS = {"write": _keyboard, "run": _dust, "look": _scan, "wave": _bubble,
         "cheer": _sparks, "stuck": _cloud, "sleep": _zs}


class Crab:
    """Idle animation. Holds its own timers so rendering stays a pure call."""

    def __init__(self):
        self.t0 = None
        self._blink_at = 0.0
        self._glance_at = 0.0
        self._glance = 0
        self._activity = None
        self._switch_at = 0.0
        self._stage = None
        self._from = None
        self._blend_at = 0.0
        self._blend_for = SETTLE
        self._last = None

    def _settle(self, now, activity, arm_l, arm_r, kick, dx):
        """Slide the limbs between activities instead of cutting, and wind the
        claws up before the two activities anybody reads off this screen.

        The shell is deliberately not here. Its height carries the seven-day
        quota, so follow through and anticipation are only ever allowed to
        borrow the claws and the legs.
        """
        if activity != self._activity:
            self._activity, self._switch_at = activity, now
        hold, rows = ANTICIPATE.get(activity, (0.0, 0))
        winding = now - self._switch_at < hold
        if winding:
            arm_l = arm_r = rows
        target = (arm_l, arm_r, kick, dx)

        if (activity, winding) != self._stage:
            self._stage = (activity, winding)
            #  A wind-up is a pose to be struck, not eased into -- at three
            #  frames per cycle a slide into it would eat the pose itself.
            self._from, self._blend_at = (None if winding else self._last), now
            self._blend_for = RELEASE if hold else SETTLE
        if self._from is not None:
            through = (now - self._blend_at) / self._blend_for
            if through >= 1.0:
                self._from = None
            else:
                #  Smoothstep, so the slide has no corner at either end; a claw
                #  that snaps to rest is the thing this is here to remove.
                through *= through * (3 - 2 * through)
                target = tuple(int(round(was + (is_ - was) * through))
                               for was, is_ in zip(self._from, target))
        self._last = target
        return target

    def _eyes(self, mode, posture, now, phase):
        """-> (blink, glance, row offset) for this activity's eye behaviour."""
        if mode == "shut":
            return False, 0, 0
        if mode == "down":
            return self._idle_blink(posture, now), 0, 1
        if mode == "scan":               # reading: the eyes sweep left to right
            return self._idle_blink(posture, now), int(round(math.sin(phase) * 1.4)), 0
        if mode == "wide":
            return False, 0, -1
        if mode == "forward":            # busy: it stares straight ahead
            return self._idle_blink(posture, now), 0, 0
        blink = self._idle_blink(posture, now)
        if posture == "spent":           # a spent crab has no energy to look around
            self._glance = 0
        elif now >= self._glance_at:
            if now < self._glance_at + 1.3:
                self._glance = self._glance or random.choice((-1, 1))
            else:
                self._glance_at = now + random.uniform(9.0, 22.0)
                self._glance = 0
        return blink, self._glance, 0

    def _idle_blink(self, posture, now):
        if now < self._blink_at:
            return False
        if now < self._blink_at + BLINK_FOR[posture]:
            return True
        self._blink_at = now + random.uniform(*BLINK_EVERY[posture])
        return False

    def frame(self, now, pct, scale, w, h, activity=DEFAULT_ACTIVITY, props=False):
        posture = posture_for(pct)
        act = ACTIVITIES.get(activity, ACTIVITIES[DEFAULT_ACTIVITY])
        if self.t0 is None:
            self.t0 = now
            self._blink_at = now + random.uniform(*BLINK_EVERY[posture])
            self._glance_at = now + random.uniform(9.0, 22.0)
        elapsed = now - self.t0

        phase = 2 * math.pi * elapsed / act["swing"] if act["swing"] else 0.0
        arm_l, arm_r = _arms(act["arms"], act["reach"], phase)
        blink, glance, eye_dy = self._eyes(act["eyes"], posture, now, phase)
        kick = int(round(act["kick"] * math.sin(phase))) if act["kick"] else 0

        period, travel = BOB[posture]
        dy = int(round(travel * act["bob"] * math.sin(2 * math.pi * elapsed / period)))
        dx = int(round(act["sway"] * math.sin(phase + math.pi / 3))) if act["sway"] else 0
        arm_l, arm_r, kick, dx = self._settle(now, activity, arm_l, arm_r, kick, dx)

        shell, claws = sprite(_grid(posture, arm_l, arm_r, eye_dy, kick,
                                    act["eyes"] == "shut"), blink=blink, glance=glance)
        layers = {"body": _place(shell, scale, w, h, dy, dx),
                  "shade": _place(claws, scale, w, h, dy, dx)}
        if props and activity in PROPS:
            prop = np.zeros((h, w), bool)
            dim = np.zeros((h, w), bool)
            PROPS[activity](prop, dim, phase, w, h)
            layers["prop"], layers["prop_dim"] = prop, dim
        return layers
