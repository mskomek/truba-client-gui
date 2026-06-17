from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from truba_gui.ssh.client import SSHClientWrapper, SSHConnInfo


class _Transport:
    def get_banner(self):
        return None

    def is_active(self):
        return False


class _SSHClient:
    def __init__(self):
        self.connect_kwargs = None

    def set_missing_host_key_policy(self, policy):
        pass

    def connect(self, **kwargs):
        self.connect_kwargs = kwargs

    def get_transport(self):
        return _Transport()

    def open_sftp(self):
        return object()


class OptionalSSHCredentialsTests(unittest.TestCase):
    def test_empty_username_and_password_use_ssh_defaults(self):
        fake_client = _SSHClient()
        with patch(
            "truba_gui.ssh.client.paramiko.SSHClient",
            return_value=fake_client,
        ):
            wrapper = SSHClientWrapper(
                SSHConnInfo(
                    host="cluster.example",
                    port=22,
                    username="",
                    password="",
                )
            )
            wrapper.connect()

        self.assertIsNone(fake_client.connect_kwargs["username"])
        self.assertIsNone(fake_client.connect_kwargs["password"])
        self.assertTrue(fake_client.connect_kwargs["allow_agent"])
        self.assertTrue(fake_client.connect_kwargs["look_for_keys"])


if __name__ == "__main__":
    unittest.main()
