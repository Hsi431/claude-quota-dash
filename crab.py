"""A crab of my own, drawn for this screen.

Its posture follows the seven-day quota: upright and breathing slowly while
there is room, sagging as the week burns down, flat on the sand when it is
nearly gone. That is the one thing the numbers beside it cannot show -- you can
read 86% or you can glance at the crab and know how the week is going.

The pixels are mine, drawn for this screen, but the character is a nod to
Anthropic's Clawd -- which is why the dashboard leaves it off until asked
(`quota crab on`).
"""
import math
import random

import numpy as np

#  Only the left half is drawn; the right half is its mirror, so the crab cannot
#  come out lopsided. '#' lit, '.' dark, 'o' eye (a hole in the shell, filled in
#  when blinking). Eleven columns a side, fourteen rows.
#  Geometry taken by measuring Claude Code's own crab: a 17x11 grid, body 13
#  wide by 9 tall, arms poking exactly two columns out of each side across three
#  rows, eyes one column wide and two tall, four thin legs. Earlier passes were
#  drawn from memory and came out as a beetle, then as a flattened version of
#  this; the numbers below are measured, not recalled.
W = 17
H = 14                           # two rows of headroom so postures can shift
BODY_COLS = (2, 14)
ARM_COLS = (0, 16)
EYE_COLS = (4, 12)
LEG_COLS = (4, 6, 10, 12)
ARM_ROWS = 3
LEG_ROWS = 2

#  The arms ride up and down inside the body's own rows, exactly as the real one
#  does; what changes with the week is how tall the body still stands.
POSTURES = {
    "tall":  dict(top=1, body=9, arm=2, eyes=2, splay=False, breath=(3.2, 2)),
    "mid":   dict(top=2, body=9, arm=4, eyes=2, splay=False, breath=(3.8, 2)),
    "tired": dict(top=3, body=8, arm=5, eyes=1, splay=True,  breath=(4.8, 1)),
    "spent": dict(top=5, body=7, arm=4, eyes=1, splay=True,  breath=(6.5, 1)),
}


def _grid(name):
    spec = POSTURES[name]
    g = [["." for _ in range(W)] for _ in range(H)]

    def fill(y, x0, x1):
        if 0 <= y < H:
            for x in range(max(0, x0), min(W - 1, x1) + 1):
                g[y][x] = "#"

    top = spec["top"]
    for i in range(spec["body"]):
        fill(top + i, *BODY_COLS)
    for i in range(ARM_ROWS):
        fill(top + spec["arm"] + i, *ARM_COLS)
    for i in range(LEG_ROWS):
        y = top + spec["body"] + i
        for col in LEG_COLS:
            drift = 0
            if spec["splay"] and col in (LEG_COLS[0], LEG_COLS[-1]):
                drift = -i if col == LEG_COLS[0] else i
            fill(y, col + drift, col + drift)
    for i in range(spec["eyes"]):
        y = top + 2 + i
        if 0 <= y < H:
            for col in EYE_COLS:
                g[y][col] = "o"
    return ["".join(row) for row in g]


GRIDS = {name: _grid(name) for name in POSTURES}

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


def sprite(posture, blink=False, glance=0):
    """-> bool array, True = lit. glance shifts the eyes by -1/0/+1 column."""
    rows = GRIDS[posture]
    h, w = len(rows), len(rows[0])
    body = np.zeros((h, w), bool)
    eyes = np.zeros((h, w), bool)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == "#":
                body[y, x] = True
            elif ch == "o":
                body[y, x] = True
                eyes[y, x] = True
    if not blink:
        if glance:
            eyes = np.roll(eyes, glance, axis=1)
        body &= ~eyes
    return body


class Crab:
    """Idle animation. Holds its own timers so rendering stays a pure call."""

    def __init__(self):
        self.t0 = None
        self._blink_at = 0.0
        self._glance_at = 0.0
        self._glance = 0

    def frame(self, now, pct, scale, w, h):
        posture = posture_for(pct)
        if self.t0 is None:
            self.t0 = now
            self._blink_at = now + random.uniform(*BLINK_EVERY[posture])
            self._glance_at = now + random.uniform(9.0, 22.0)

        blink = False
        if now >= self._blink_at:
            if now < self._blink_at + BLINK_FOR[posture]:
                blink = True
            else:
                self._blink_at = now + random.uniform(*BLINK_EVERY[posture])
        # A spent crab has no energy to look around.
        if posture == "spent":
            self._glance = 0
        elif now >= self._glance_at:
            if now < self._glance_at + 1.3:
                self._glance = self._glance or random.choice((-1, 1))
            else:
                self._glance_at = now + random.uniform(9.0, 22.0)
                self._glance = 0

        period, travel = BOB[posture]
        dy = int(round(travel * math.sin(2 * math.pi * (now - self.t0) / period)))
        spr = sprite(posture, blink=blink, glance=self._glance)
        big = np.kron(spr, np.ones((scale, scale), bool))
        fb = np.zeros((h, w), bool)
        y = (h - big.shape[0]) // 2 + dy
        x = (w - big.shape[1]) // 2
        ys, xs = max(0, y), max(0, x)
        big = big[ys - y:h - y, xs - x:w - x]
        fb[ys:ys + big.shape[0], xs:xs + big.shape[1]] = big
        return fb
