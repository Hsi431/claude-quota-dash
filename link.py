"""Serial link to the dumb T-Display-S3 node."""
import collections
import glob
import os
import queue
import threading
import time

import numpy as np
import serial
import netlink


PORT_ENV = "QUOTA_DASH_PORT"
PORT_GLOB = "/dev/serial/by-id/*Espressif*JTAG*-if00"
BAUD = 115200
WIDTH, HEIGHT = 320, 170
CONFIG_PATH = os.path.expanduser("~/.config/quota-dash/net.conf")


def find_port():
    """The board's own path, or the one Espressif port on this machine.

    Every ESP32 with native USB-JTAG enumerates as 303a:1001, so a second one
    on the same desk is indistinguishable by VID:PID -- only the MAC in the
    by-id path tells them apart, and that is per board. So: pick the port when
    there is exactly one, and ask rather than guess when there is not.
    """
    override = os.environ.get(PORT_ENV)
    if override:
        return override
    found = sorted(glob.glob(PORT_GLOB))
    if not found:
        raise FileNotFoundError(
            f"no Espressif USB-JTAG port matching {PORT_GLOB} -- plug the board in, "
            f"or set {PORT_ENV} to its device path")
    if len(found) > 1:
        listing = "".join(f"\n  {path}" for path in found)
        raise FileNotFoundError(
            f"{len(found)} Espressif boards are plugged in, so set {PORT_ENV} to the "
            f"T-Display-S3:{listing}")
    return found[0]


def load_config(path=None):
    config_path = os.path.abspath(os.path.expanduser(
        CONFIG_PATH if path is None else path))
    config = {"transport": "serial", "bind": "0.0.0.0",
              "port": netlink.DEFAULT_PORT, "token": ""}
    try:
        with open(config_path, encoding="utf-8") as stream:
            for raw in stream:
                line = raw.split("#", 1)[0].strip()
                if not line:
                    continue
                key, separator, value = line.partition("=")
                if not separator:
                    continue
                key, value = key.strip(), value.strip()
                if key in ("transport", "bind", "token"):
                    config[key] = value
                elif key == "port":
                    try:
                        config[key] = int(value)
                    except ValueError as exc:
                        raise ValueError(
                            f"invalid port in {config_path}: {value}") from exc
    except FileNotFoundError:
        pass

    override = os.environ.get("QUOTA_DASH_TRANSPORT")
    if override is not None:
        config["transport"] = override.strip()
    if config["transport"] not in ("serial", "net"):
        raise ValueError(
            f"invalid transport in {config_path}: {config['transport']}")
    if not 1 <= config["port"] <= 65535:
        raise ValueError(f"invalid port in {config_path}: {config['port']}")
    if config["transport"] == "net" and not config["token"]:
        raise ValueError(f"net transport requires token in {config_path}")
    return config


def rgb565(image):
    """Convert an RGB PIL image/array to big-endian RGB565 bytes."""
    rgb = np.asarray(image, dtype=np.uint8)
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        raise ValueError("expected an RGB image")
    value = ((rgb[..., 0].astype(np.uint16) >> 3) << 11)
    value |= ((rgb[..., 1].astype(np.uint16) >> 2) << 5)
    value |= rgb[..., 2].astype(np.uint16) >> 3
    return value.astype(">u2", copy=False).tobytes()


class SerialTransport:
    late_replies_possible = True

    def __init__(self, port=None):
        self.ser = serial.Serial()
        self.ser.port = port or find_port()
        self.ser.baudrate = BAUD
        self.ser.timeout = 0.1
        self.ser.write_timeout = 2.0
        self.ser.dtr = self.ser.rts = False
        self.ser.open()
        time.sleep(0.2)
        self.ser.reset_input_buffer()

    def write(self, data):
        self.ser.write(data)

    def flush(self):
        self.ser.flush()

    def readline(self):
        return self.ser.readline()

    def close(self):
        self.ser.close()


class Board:
    def __init__(self, transport):
        self.transport = transport
        self._responses = queue.Queue()
        self._buttons = queue.Queue()
        self._history = collections.deque(maxlen=200)
        self._boots = []
        self._opened_at = time.monotonic()
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._read_lines, daemon=True)
        self._reader.start()

    def _read_lines(self):
        while not self._stop.is_set():
            try:
                line = self.transport.readline().decode(errors="replace").strip()
            except (OSError, TypeError, serial.SerialException):
                return
            if not line:
                continue
            if line.startswith("BTN "):
                self._buttons.put(line)
            elif line.startswith("BOOT "):
                # The board only says this out of setup(), so a BOOT line in
                # the middle of a session means it restarted under us. Keep it
                # out of the reply queue or it answers the wrong command.
                at = time.monotonic()
                self._boots.append((at, line))
                # Opening the port resets the board, so the first one is ours.
                whose = "on open" if at - self._opened_at < 3.0 else "BY ITSELF"
                print(f"link: board booted {whose}: {line}", flush=True)
            else:
                self._responses.put(line)

    def _cmd(self, text, payload=b""):
        started = time.monotonic()
        with self._write_lock:
            self.transport.write((text + "\n").encode())
            for offset in range(0, len(payload), 4096):
                self.transport.write(payload[offset:offset + 4096])
            self.transport.flush()
        written = time.monotonic()
        deadline = written + 3.0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._remember(started, written, None, text, len(payload), "deadline")
                if self.transport.late_replies_possible:
                    self._forensics(text, len(payload))
                raise TimeoutError(f"timeout waiting for {text}")
            try:
                reply = self._responses.get(timeout=remaining)
            except queue.Empty:
                self._remember(started, written, None, text, len(payload), "silence")
                if not self.transport.late_replies_possible:
                    raise TimeoutError(f"timeout waiting for {text}") from None
                late = self._collect_late(text)
                if late is not None:
                    return late
                again = self._resend(text, payload)
                if again is not None:
                    return again
                self._forensics(text, len(payload))
                raise TimeoutError(f"timeout waiting for {text}") from None
            self._remember(started, written, time.monotonic(), text, len(payload), reply)
            if reply != "OK" and not reply.startswith("PONG"):
                print(f"link: {text} -> {reply}", flush=True)
            return reply

    def _collect_late(self, text):
        """Measured on 2026-09-11: the board finishes the push in ~74ms and
        reports no failures, but its USB TX can sit unsent until the next host
        write nudges it, so the reply lands after the deadline. Nudge the link
        and see whether the answer was in there all along. Only a genuinely
        missing reply falls through to the caller, which still dies."""
        try:
            with self._write_lock:
                self.transport.write(b"PING\n")
                self.transport.flush()
        except (OSError, serial.SerialException):
            return None
        answer = None
        heard = []
        deadline = time.monotonic() + 2.0
        while answer is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                line = self._responses.get(timeout=remaining)
            except queue.Empty:
                break
            heard.append(line)
            if not line.startswith("PONG"):
                answer = line
        if answer is None:
            return None
        if not any(line.startswith("PONG") for line in heard):
            # The nudge is still on its way back. Swallow it here or it turns up
            # as the answer to whatever command runs next.
            try:
                heard.append(self._responses.get(timeout=1.0))
            except queue.Empty:
                pass
        board = next((line for line in heard if line.startswith("PONG")), "no PONG")
        print(f"link: {text} answered late, not lost: {answer} ({board})", flush=True)
        return answer

    def _resend(self, text, payload):
        """Measured on 2026-09-11: sometimes the reply is gone rather than late -
        the board answers a fresh PING at once, yet the OK for that RECT never
        arrives at all. A RECT is idempotent (same box, same pixels), so once the
        board has proven it is back in its command loop, the safe move is to send
        it again rather than take the whole daemon down."""
        if not self._probe().startswith("PONG"):
            return None
        while True:
            try:
                self._responses.get_nowait()
            except queue.Empty:
                break
        try:
            with self._write_lock:
                self.transport.write((text + "\n").encode())
                for offset in range(0, len(payload), 4096):
                    self.transport.write(payload[offset:offset + 4096])
                self.transport.flush()
        except (OSError, serial.SerialException):
            return None
        try:
            reply = self._responses.get(timeout=3.0)
        except queue.Empty:
            return None
        print(f"link: {text} was lost, not late; resent it and got {reply}", flush=True)
        return reply

    def _remember(self, started, written, answered, text, payload_bytes, reply):
        """Diagnostics only (2026-09-11): keep the last few hundred commands so a
        timeout can be read against what the link was doing just before it."""
        self._history.append({
            "at": started,
            "write_ms": (written - started) * 1000,
            "wait_ms": None if answered is None else (answered - written) * 1000,
            "cmd": text,
            "bytes": payload_bytes,
            "reply": reply,
        })

    def _forensics(self, text, payload_bytes):
        """Diagnostics only (2026-09-11): the daemon dies right after this and
        systemd reopens the port, which resets the board and destroys the scene.
        So take the evidence here, while the board is still in the state that
        produced the fault. This does not swallow the fault - the caller still
        raises and the daemon still dies."""
        now = time.monotonic()
        print(f"link: TIMEOUT on {text} after {payload_bytes} payload bytes, "
              f"{self._responses.qsize()} replies waiting", flush=True)

        if self._boots:
            for at, line in self._boots[-3:]:
                print(f"link:   board booted {now - at:.1f}s ago: {line}", flush=True)
        else:
            print("link:   board has not announced a boot this session", flush=True)

        recent = list(self._history)[-30:]
        print(f"link:   last {len(recent)} commands (oldest first):", flush=True)
        for entry in recent:
            wait = "-" if entry["wait_ms"] is None else f"{entry['wait_ms']:7.1f}"
            print(f"link:     -{now - entry['at']:6.2f}s {entry['cmd']:<28} "
                  f"{entry['bytes']:6d}B write {entry['write_ms']:6.1f}ms "
                  f"wait {wait}ms -> {entry['reply']}", flush=True)

        pushes = [e["wait_ms"] for e in self._history if e["wait_ms"] is not None]
        if pushes:
            print(f"link:   wait over last {len(pushes)}: "
                  f"min {min(pushes):.1f} max {max(pushes):.1f} "
                  f"mean {sum(pushes) / len(pushes):.1f}ms", flush=True)

        # Does it answer at all, and if not, does it come back on its own?
        for attempt in range(5):
            answer = self._probe()
            print(f"link:   probe {attempt + 1} at +{time.monotonic() - now:.1f}s: {answer}",
                  flush=True)
            if answer.startswith("PONG"):
                break
            time.sleep(4.0)

        drained = []
        while True:
            try:
                drained.append(self._responses.get_nowait())
            except queue.Empty:
                break
        if drained:
            print(f"link:   board also said: {drained[:20]}", flush=True)

    def _probe(self):
        """Diagnostics only: does the board still answer after a timeout?"""
        try:
            with self._write_lock:
                self.transport.write(b"PING\n")
                self.transport.flush()
        except (OSError, serial.SerialException) as exc:
            return f"the port is gone ({exc})"
        try:
            return self._responses.get(timeout=1.0)
        except queue.Empty:
            return "nothing"

    def ping(self):
        reply = self._cmd("PING")
        # Printed so every session records the board's memory at a known-good
        # moment; a later probe is only meaningful against this baseline.
        print(f"link: {reply}", flush=True)
        return reply

    def rect(self, x, y, w, h, rgb565_bytes):
        want = int(w) * int(h) * 2
        if len(rgb565_bytes) != want:
            raise ValueError(f"RECT payload is {len(rgb565_bytes)} bytes, want {want}")
        return self._cmd(f"RECT {int(x)} {int(y)} {int(w)} {int(h)}", rgb565_bytes)

    def brightness(self, n):
        return self._cmd(f"BRI {int(n)}")

    def clear(self):
        return self._cmd("CLR")

    def poll_button(self):
        try:
            return self._buttons.get_nowait()
        except queue.Empty:
            return None

    def close(self):
        self._stop.set()
        try:
            self.transport.close()
        finally:
            self._reader.join(timeout=0.3)


_listener = None
_listener_config = None


def open_board():
    global _listener, _listener_config
    config = load_config()
    if config["transport"] == "serial":
        return Board(SerialTransport())

    listener_config = (config["bind"], config["port"], config["token"])
    if _listener is None or _listener_config != listener_config:
        _listener = netlink.Listener(*listener_config)
        _listener_config = listener_config
    return Board(_listener.accept_board())
