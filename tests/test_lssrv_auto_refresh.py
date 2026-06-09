from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath("src"))

from PySide6.QtWidgets import QApplication

from truba_gui.config import storage
from truba_gui.ui.widgets.jobs_outputs_widget import JobsOutputsWidget


class _FakeSlurm:
    def __init__(self):
        self.jobs_calls = 0
        self.sacct_calls = 0
        self.lssrv_calls = 0

    def squeue(self, _user):
        self.jobs_calls += 1
        return "jobs"

    def sacct(self, _user):
        self.sacct_calls += 1
        return "accounting"

    def lssrv(self):
        self.lssrv_calls += 1
        return "servers"


class LssrvAutoRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.interval = patch(
            "truba_gui.ui.widgets.jobs_outputs_widget."
            "get_jobs_outputs_refresh_interval_seconds",
            return_value=23,
        )
        self.enabled = patch(
            "truba_gui.ui.widgets.jobs_outputs_widget."
            "get_lssrv_auto_refresh_enabled",
            return_value=False,
        )
        self.interval.start()
        self.enabled_mock = self.enabled.start()
        self.widget = JobsOutputsWidget()
        self.slurm = _FakeSlurm()
        self.session = {
            "connected": True,
            "cfg": SimpleNamespace(username="mkomek"),
            "slurm": self.slurm,
            "files": None,
        }

    def tearDown(self):
        self.widget.shutdown()
        self.widget.deleteLater()
        self.enabled.stop()
        self.interval.stop()

    def test_connected_session_starts_jobs_timer_with_saved_interval(self):
        self.widget.set_session(self.session)

        self.assertTrue(self.widget._jobs_refresh_timer.isActive())
        self.assertEqual(self.widget._jobs_refresh_timer.interval(), 23000)

    def test_disabled_tick_refreshes_jobs_without_lssrv(self):
        self.widget.set_session(self.session)
        initial_jobs = self.slurm.jobs_calls
        initial_lssrv = self.slurm.lssrv_calls

        self.widget._poll_jobs_and_lssrv()

        self.assertEqual(self.slurm.jobs_calls, initial_jobs + 1)
        self.assertEqual(self.slurm.lssrv_calls, initial_lssrv)

    def test_enabled_tick_refreshes_jobs_and_lssrv(self):
        self.widget.set_session(self.session)
        initial_jobs = self.slurm.jobs_calls
        initial_lssrv = self.slurm.lssrv_calls
        self.enabled_mock.return_value = True

        self.widget._poll_jobs_and_lssrv()

        self.assertEqual(self.slurm.jobs_calls, initial_jobs + 1)
        self.assertEqual(self.slurm.lssrv_calls, initial_lssrv + 1)

    def test_disconnected_tick_stops_without_remote_calls(self):
        self.widget.session = {
            "connected": False,
            "cfg": SimpleNamespace(username="mkomek"),
            "slurm": self.slurm,
        }
        self.widget._jobs_refresh_timer.start()

        self.widget._poll_jobs_and_lssrv()

        self.assertFalse(self.widget._jobs_refresh_timer.isActive())
        self.assertEqual(self.slurm.jobs_calls, 0)
        self.assertEqual(self.slurm.lssrv_calls, 0)

    def test_setting_defaults_to_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "config.json")
            with patch.object(storage, "_config_path", return_value=Path(config_path)):
                self.assertFalse(storage.get_lssrv_auto_refresh_enabled())

    def test_setting_persists_enabled_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "config.json")
            with patch.object(storage, "_config_path", return_value=Path(config_path)):
                storage.set_lssrv_auto_refresh_enabled(True)
                self.assertTrue(storage.get_lssrv_auto_refresh_enabled())


if __name__ == "__main__":
    unittest.main()
