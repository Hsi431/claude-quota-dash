"""Own the serial link, render at 1 Hz, and serve the local control socket."""
import os
import select
import signal
import socket
import time

import numpy as np

import data
import render
from link import Board, rgb565


WIDTH, HEIGHT = 320, 170
SOCK = os.path.join(os.path.dirname(os.path.realpath(__file__)), "quota.sock")
PAGES = (render.page_quota, render.page_five, render.page_context, render.page_cache)
ANIMATED = 1                 # the crab breathes, so this page needs frames
ANIMATED_INTERVAL = 0.125
IDLE_INTERVAL = 1.0


class Dashboard:
    def __init__(self):
        self.page = 1
        self.brightness = 255
        self.previous = None
        self.force = True

    def next_page(self, step=1):
        self.page = (self.page - 1 + step) % len(PAGES) + 1
        self.force = True

    def set_page(self, page):
        if page not in range(1, len(PAGES) + 1):
            return "ERR page 1-4"
        self.page = page
        self.force = True
        return "OK"

    def set_brightness(self, value):
        if not 0 <= value <= 255:
            return "ERR bri 0-255"
        self.brightness = value
        return "OK"

    def dispatch(self, line):
        verb, _, arg = line.strip().partition(" ")
        if verb == "page":
            try:
                return self.set_page(int(arg))
            except ValueError:
                return "ERR page 1-4"
        if verb == "bri":
            try:
                return self.set_brightness(int(arg))
            except ValueError:
                return "ERR bri 0-255"
        if verb == "next" and not arg:
            self.next_page()
            return "OK"
        if verb == "prev" and not arg:
            self.next_page(-1)
            return "OK"
        if verb == "crab" and arg in ("on", "off"):
            render.set_crab(arg == "on")
            self.force = True
            return "OK"
        if verb == "status" and not arg:
            return (f"PAGE {self.page} BRI {self.brightness} "
                    f"CRAB {'on' if render.crab_enabled() else 'off'}")
        return "ERR unknown command"


def _changed_rect(previous, image):
    current = np.asarray(image, dtype=np.uint8)
    if previous is None:
        return 0, 0, WIDTH, HEIGHT, current
    changed = np.any(current != previous, axis=2)
    ys, xs = np.where(changed)
    if not len(xs):
        return None, None, None, None, current
    x, y = int(xs.min()), int(ys.min())
    return x, y, int(xs.max()) - x + 1, int(ys.max()) - y + 1, current


def _server():
    try:
        os.unlink(SOCK)
    except FileNotFoundError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCK)
    server.listen(4)
    server.setblocking(False)
    return server


def _poll_socket(server, dashboard):
    try:
        ready, _, _ = select.select([server], [], [], 0)
    except OSError:
        return
    if not ready:
        return
    conn, _ = server.accept()
    with conn:
        conn.settimeout(0.2)
        line = conn.recv(256).decode(errors="replace")
        conn.sendall((dashboard.dispatch(line) + "\n").encode())


def run():
    board = Board()
    board.ping()
    board.clear()
    dashboard = Dashboard()
    server = _server()
    sent_brightness = dashboard.brightness
    snapshot, snapshot_at = data.load(), time.monotonic()
    alive = True

    def stop(*_):
        nonlocal alive
        alive = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while alive:
            started = time.monotonic()
            while True:
                event = board.poll_button()
                if event is None:
                    break
                if event == "BTN 2":
                    dashboard.next_page()
                elif event == "BTN 1":
                    dashboard.next_page(-1)
            _poll_socket(server, dashboard)
            if dashboard.brightness != sent_brightness:
                board.brightness(dashboard.brightness)
                sent_brightness = dashboard.brightness

            if time.monotonic() - snapshot_at >= IDLE_INTERVAL:
                snapshot, snapshot_at = data.load(), time.monotonic()
            current = PAGES[dashboard.page - 1](snapshot)
            x, y, w, h, pixels = _changed_rect(dashboard.previous, current)
            if dashboard.force or x is not None:
                if dashboard.force and dashboard.previous is not None:
                    x, y, w, h = 0, 0, WIDTH, HEIGHT
                board.rect(x, y, w, h, rgb565(current.crop((x, y, x + w, y + h))))
                dashboard.previous = pixels
                dashboard.force = False
            # Only the crab moves; without it the first page is as still as the rest.
            animating = dashboard.page == ANIMATED and render.crab_enabled()
            interval = ANIMATED_INTERVAL if animating else IDLE_INTERVAL
            delay = interval - (time.monotonic() - started)
            if delay > 0:
                time.sleep(delay)
    finally:
        server.close()
        try:
            os.unlink(SOCK)
        except FileNotFoundError:
            pass
        board.close()


if __name__ == "__main__":
    run()
