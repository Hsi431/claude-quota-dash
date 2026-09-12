"""Own the serial link, render at 1 Hz, and serve the local control socket."""
import os
import select
import signal
import socket
import time

import numpy as np

import crab
import data
import render
import link
import netlink
from link import rgb565


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
        if verb == "lang" and arg in render.LANGUAGES:
            render.set_language(arg)
            self.force = True
            return "OK"
        if verb == "crab" and arg in ("on", "off"):
            render.set_crab(arg == "on")
            self.force = True
            return "OK"
        if verb == "pose":
            name, _, hold = arg.partition(" ")
            try:
                seconds = float(hold) if hold else None
            except ValueError:
                return "ERR pose NAME [seconds]"
            if not render.set_activity(name, seconds):
                return "ERR pose " + " ".join(sorted(crab.ACTIVITIES))
            return "OK"
        if verb == "poses" and not arg:
            return " ".join(sorted(crab.ACTIVITIES))
        if verb in ("props", "label") and arg in ("on", "off"):
            (render.set_props if verb == "props" else render.set_label)(arg == "on")
            self.force = True
            return "OK"
        if verb == "status" and not arg:
            return (f"PAGE {self.page} BRI {self.brightness} "
                    f"CRAB {'on' if render.crab_enabled() else 'off'} "
                    f"PROPS {'on' if render.props_enabled() else 'off'} "
                    f"LABEL {'on' if render.label_enabled() else 'off'} "
                    f"LANG {render.language()} ACT {render.activity()}")
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
    dashboard = Dashboard()
    sent_brightness = dashboard.brightness

    def is_net(board):
        return isinstance(board.transport, netlink.SocketTransport)

    def connect():
        nonlocal sent_brightness
        board = link.open_board()
        if not is_net(board):
            board.ping()
            board.clear()
            return board
        while True:
            try:
                board.ping()
                board.clear()
            except (TimeoutError, OSError) as exc:
                print(f"link: board went away: {exc}", flush=True)
                try:
                    board.close()
                except (TimeoutError, OSError):
                    pass
                board = link.open_board()
                continue
            dashboard.previous = None
            dashboard.force = True
            sent_brightness = None
            return board

    board = connect()
    server = _server()
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
            try:
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
                    board.rect(x, y, w, h,
                               rgb565(current.crop((x, y, x + w, y + h))))
                    dashboard.previous = pixels
                    dashboard.force = False
                # Only the crab moves; without it the first page is as still as the rest.
                animating = dashboard.page == ANIMATED and render.crab_enabled()
                interval = ANIMATED_INTERVAL if animating else IDLE_INTERVAL
                delay = interval - (time.monotonic() - started)
                if delay > 0:
                    time.sleep(delay)
            except (TimeoutError, OSError) as exc:
                if not is_net(board):
                    raise
                print(f"link: board went away: {exc}", flush=True)
                try:
                    board.close()
                except (TimeoutError, OSError):
                    pass
                board = connect()
                continue
    finally:
        server.close()
        try:
            os.unlink(SOCK)
        except FileNotFoundError:
            pass
        board.close()


if __name__ == "__main__":
    run()
