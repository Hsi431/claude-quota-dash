import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

import link
import netlink


class HandshakeTests(unittest.TestCase):
    def test_correct_greeting_is_accepted(self):
        client, server = socket.socketpair()
        try:
            client.sendall(b"HELLO 1 tdisplay <token>\n")
            self.assertTrue(netlink.handshake(server, "<token>"))
            self.assertEqual(client.recv(32), b"OK\n")
        finally:
            client.close()
            server.close()

    def test_wrong_token_is_rejected(self):
        client, server = socket.socketpair()
        try:
            client.sendall(b"HELLO 1 tdisplay wrong\n")
            self.assertFalse(netlink.handshake(server, "<token>"))
            self.assertEqual(client.recv(32), b"ERR auth\n")
        finally:
            client.close()
            server.close()

    def test_wrong_version_or_node_is_rejected(self):
        for greeting in (b"HELLO 2 tdisplay <token>\n",
                         b"HELLO 1 agentcore <token>\n"):
            with self.subTest(greeting=greeting):
                client, server = socket.socketpair()
                try:
                    client.sendall(greeting)
                    self.assertFalse(netlink.handshake(server, "<token>"))
                    self.assertEqual(client.recv(32), b"ERR auth\n")
                finally:
                    client.close()
                    server.close()

    def test_overlong_greeting_is_rejected(self):
        client, server = socket.socketpair()
        try:
            client.sendall(b"x" * 257)
            self.assertFalse(netlink.handshake(server, "<token>"))
            self.assertEqual(client.recv(32), b"ERR auth\n")
        finally:
            client.close()
            server.close()


class ConfigTests(unittest.TestCase):
    def test_config_values_and_transport_environment_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "net.conf"
            path.write_text("# comment\ntransport = net\nbind = <bind>\n"
                            "port = 9001\ntoken = <token>\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("QUOTA_DASH_TRANSPORT", None)
                config = link.load_config(path)
            self.assertEqual(config, {"transport": "net", "bind": "<bind>",
                                      "port": 9001, "token": "<token>"})
            with mock.patch.dict(os.environ, {"QUOTA_DASH_TRANSPORT": "serial"}):
                self.assertEqual(link.load_config(path)["transport"], "serial")

    def test_missing_config_defaults_to_serial(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("QUOTA_DASH_TRANSPORT", None)
                config = link.load_config(Path(directory) / "missing.conf")
        self.assertEqual(config["transport"], "serial")

    def test_net_config_requires_token_and_names_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "net.conf"
            path.write_text("transport = net\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, str(path)):
                link.load_config(path)


class TransportTests(unittest.TestCase):
    def test_late_replies_are_serial_only(self):
        self.assertTrue(link.SerialTransport.late_replies_possible)
        self.assertFalse(netlink.SocketTransport.late_replies_possible)


if __name__ == "__main__":
    unittest.main()
