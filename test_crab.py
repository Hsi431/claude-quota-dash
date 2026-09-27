#!/usr/bin/env python3
import random

import numpy as np

import crab


T0 = 1000.0
WIDTH = 60
HEIGHT = 100


def render(crab_sprite, frame_number, activity):
    return crab_sprite.frame(
        T0 + frame_number * crab.FRAME, 0, 1, WIDTH, HEIGHT, activity)


def shell_origin(layers):
    pixels = layers["body"] | layers["shade"]
    for y, row in enumerate(pixels):
        x = 0
        while x < pixels.shape[1]:
            if not row[x]:
                x += 1
                continue
            end = x
            while end < pixels.shape[1] and row[end]:
                end += 1
            if end - x == BODY_WIDTH:
                left = x - crab.BODY_COLS[0]
                top = np.flatnonzero(pixels[:, left + 8]).min()
                return int(top), left
            x = end
    raise AssertionError("could not locate the shell")


BODY_WIDTH = crab.BODY_COLS[1] - crab.BODY_COLS[0] + 1


def arm_offsets(layers, posture):
    pixels = layers["body"] | layers["shade"]
    top, left = shell_origin(layers)
    left_rows = np.flatnonzero(pixels[:, left:left + 2].all(axis=1))
    right_rows = np.flatnonzero(pixels[:, left + 15:left + 17].all(axis=1))
    base = top + crab.POSTURES[posture]["arm"]
    return int(left_rows.min() - base), int(right_rows.min() - base)


def shell_height(layers, posture):
    top, left = shell_origin(layers)
    body = layers["body"]
    central_column = body[top:, left + 8]
    return int(central_column.sum())


def action_start(activity, switch_frame=1):
    hold = crab.ANTICIPATE.get(activity, (0.0, 0))[0]
    release = crab.RELEASE if hold else crab.SETTLE
    return switch_frame + round((hold + release) / crab.FRAME)


def test_frame_constants():
    def aligned(seconds):
        frames = seconds / crab.FRAME
        assert abs(frames - round(frames)) < 1e-9, seconds

    for spec in crab.POSTURES.values():
        aligned(spec["breath"][0])
    for spec in crab.ACTIVITIES.values():
        if spec["swing"] is not None:
            aligned(spec["swing"])
    for seconds in crab.BLINK_FOR.values():
        aligned(seconds)
    aligned(crab.SETTLE)
    aligned(crab.RELEASE)
    for seconds, _ in crab.ANTICIPATE.values():
        aligned(seconds)
    aligned(crab.GLANCE_FOR)

    assert crab.ACTION_FRAMES["write"] == (
        (6, 0), (0, 6), (6, 0), (0, 6), (6, 0), (0, 6), (0, 0), (0, 0),
        (6, 0), (0, 6), (6, 0), (0, 6), (0, 0), (0, 0), (0, 0), (0, 0),
    )
    assert crab.ACTION_FRAMES["wave"] == (
        (0, -5), (0, -3), (0, -5), (0, -3),
        (0, -4), (0, -4), (0, -4), (0, -4),
        (0, -4), (0, -4), (0, -4), (0, -4),
        (0, -4), (0, -4), (0, -4), (0, -4),
    )
    assert crab.ACTION_FRAMES["cheer"] == (
        (-4, -5), (-3, -4), (-4, -5), (-3, -4),
        (-4, -5), (-4, -5), (-4, -5), (-4, -5),
    )


def test_de_twin():
    for activity in ("cheer", "stuck", "sleep"):
        random.seed(11)
        crab_sprite = crab.Crab()
        render(crab_sprite, 0, "idle")
        start = action_start(activity)
        positions = []
        for frame_number in range(1, start + 48):
            layers = render(crab_sprite, frame_number, activity)
            if frame_number >= start:
                positions.append(arm_offsets(layers, "tall"))
        assert all(left != right for left, right in positions), activity


def test_switch_blink():
    for activity in ("run", "write", "look", "wave", "cheer", "stuck"):
        random.seed(13)
        crab_sprite = crab.Crab()
        render(crab_sprite, 0, "idle")
        first = render(crab_sprite, 1, activity)
        second = render(crab_sprite, 2, activity)
        first_top, first_left = shell_origin(first)
        second_top, second_left = shell_origin(second)
        first_central = first["body"][
            first_top:first_top + crab.POSTURES["tall"]["body"],
            first_left + 2:first_left + 15,
        ]
        second_central = second["body"][
            second_top:second_top + crab.POSTURES["tall"]["body"],
            second_left + 2:second_left + 15,
        ]
        assert int(first_central.sum()) == 13 * 9
        assert int(second_central.sum()) == 13 * 9 - 4


def test_action_tables():
    for activity in ("write", "wave", "cheer"):
        random.seed(17)
        crab_sprite = crab.Crab()
        render(crab_sprite, 0, "idle")
        start = action_start(activity)
        positions = []
        for frame_number in range(1, start + len(crab.ACTION_FRAMES[activity])):
            layers = render(crab_sprite, frame_number, activity)
            if frame_number >= start:
                positions.append(arm_offsets(layers, "tall"))
        assert positions == list(crab.ACTION_FRAMES[activity]), activity

    random.seed(19)
    crab_sprite = crab.Crab()
    render(crab_sprite, 0, "idle")
    start = action_start("wave")
    wave_positions = []
    for frame_number in range(1, start + 16):
        layers = render(crab_sprite, frame_number, "wave")
        if frame_number >= start:
            wave_positions.append(arm_offsets(layers, "tall"))
    assert len({right for _, right in wave_positions[6:16]}) == 1

    random.seed(23)
    crab_sprite = crab.Crab()
    render(crab_sprite, 0, "idle")
    start = action_start("write")
    write_positions = []
    for frame_number in range(1, start + 16):
        layers = render(crab_sprite, frame_number, "write")
        if frame_number >= start:
            write_positions.append(arm_offsets(layers, "tall"))
    assert write_positions[12:16] == [(0, 0)] * 4


def test_posture_height():
    postures = (("tall", 0), ("mid", 61), ("tired", 81), ("spent", 91))
    activities = tuple(crab.ACTIVITIES)
    for posture, pct in postures:
        heights = []
        for activity in activities:
            random.seed(29)
            crab_sprite = crab.Crab()
            layers = crab_sprite.frame(T0 + 19 * crab.FRAME, pct, 1,
                                       WIDTH, HEIGHT, activity)
            heights.append(shell_height(layers, posture))
        assert heights == [crab.POSTURES[posture]["body"]] * 8, (posture, heights)


def main():
    test_frame_constants()
    test_de_twin()
    test_switch_blink()
    test_action_tables()
    test_posture_height()


if __name__ == "__main__":
    main()
