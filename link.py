"""Serial link to the dumb T-Display-S3 node."""
import glob
import os
import queue
import threading
import time

import numpy as np
import serial


BOARD_MAC = "EC:DA:3B:9D:77:38"
PORT_GLOB = f"/dev/serial/by-id/*Espressif*JTAG*{BOARD_MAC}*-if00"
BAUD = 115200
WIDTH, HEIGHT = 320, 170


def find_port():
    found = sorted(glob.glob(PORT_GLOB))
    if not found:
        raise FileNotFoundError(f"no T-Display-S3 with MAC {BOARD_MAC}")
    return found[0]


def rgb565(image):
    """Convert an RGB PIL image/array to big-endian RGB565 bytes."""
    rgb = np.asarray(image, dtype=np.uint8)
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        raise ValueError("expected an RGB image")
    value = ((rgb[..., 0].astype(np.uint16) >> 3) << 11)
    value |= ((rgb[..., 1].astype(np.uint16) >> 2) << 5)
    value |= rgb[..., 2].astype(np.uint16) >> 3
    return value.astype(">u2", copy=False).tobytes()


class Board:
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
        self._responses = queue.Queue()
        self._buttons = queue.Queue()
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._read_lines, daemon=True)
        self._reader.start()

    def _read_lines(self):
        while not self._stop.is_set():
            try:
                line = self.ser.readline().decode(errors="replace").strip()
            except (OSError, TypeError, serial.SerialException):
                return
            if not line:
                continue
            if line.startswith("BTN "):
                self._buttons.put(line)
            else:
                self._responses.put(line)

    def _cmd(self, text, payload=b""):
        with self._write_lock:
            self.ser.write((text + "\n").encode())
            for offset in range(0, len(payload), 4096):
                self.ser.write(payload[offset:offset + 4096])
            self.ser.flush()
        deadline = time.monotonic() + 3.0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timeout waiting for {text}")
            try:
                return self._responses.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError(f"timeout waiting for {text}") from None

    def ping(self):
        return self._cmd("PING")

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
            self.ser.close()
        finally:
            self._reader.join(timeout=0.3)
