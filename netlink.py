"""TCP transport for the dumb T-Display-S3 node."""
import socket


DEFAULT_PORT = 8782
PROTO = 1
GREETING = "HELLO 1 tdisplay <token>"


def _reply(sock, data):
    try:
        sock.sendall(data)
    except OSError:
        return False
    return True


def _handshake_result(sock, token):
    if sock.gettimeout() is None:
        sock.settimeout(5.0)
    line = bytearray()
    try:
        while True:
            chunk = sock.recv(1)
            if not chunk:
                _reply(sock, b"ERR auth\n")
                return False, "closed"
            line.extend(chunk)
            if len(line) > 256:
                _reply(sock, b"ERR auth\n")
                return False, "line-too-long"
            if chunk == b"\n":
                break
    except socket.timeout:
        _reply(sock, b"ERR auth\n")
        return False, "timeout"
    except OSError:
        return False, "socket"

    expected = f"HELLO {PROTO} tdisplay {token}\n".encode()
    if line != expected:
        _reply(sock, b"ERR auth\n")
        return False, "auth"
    if not _reply(sock, b"OK\n"):
        return False, "write"
    return True, ""


def handshake(sock, token):
    """Authenticate an already-connected socket without binding or listening."""
    return _handshake_result(sock, token)[0]


class SocketTransport:
    late_replies_possible = False

    def __init__(self, sock):
        self.sock = sock
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(10.0)
        self.file = sock.makefile("rwb")

    def write(self, data):
        self.file.write(data)
        self.file.flush()

    def flush(self):
        self.file.flush()

    def readline(self):
        return self.file.readline()

    def close(self):
        try:
            self.file.close()
        finally:
            self.sock.close()


class Listener:
    def __init__(self, bind, port, token):
        self.token = token
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((bind, port))
        self.sock.listen(1)

    def accept_board(self, timeout=None):
        previous_timeout = self.sock.gettimeout()
        self.sock.settimeout(timeout)
        try:
            while True:
                conn, address = self.sock.accept()
                ip = address[0]
                accepted = False
                transport = None
                try:
                    accepted, reason = _handshake_result(conn, self.token)
                    if accepted:
                        transport = SocketTransport(conn)
                        print(f"netlink: board connected from {ip}", flush=True)
                        return transport
                    print(f"netlink: rejected {ip}: {reason}", flush=True)
                except OSError as exc:
                    print(f"netlink: rejected {ip}: {exc}", flush=True)
                finally:
                    if transport is None:
                        conn.close()
        finally:
            self.sock.settimeout(previous_timeout)
