from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _load_probe_module():
    path = Path(__file__).resolve().parents[1] / "devtools" / "performance_probe.py"
    spec = importlib.util.spec_from_file_location("test_performance_probe_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("performance probe could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PerformanceProbeTests(unittest.TestCase):
    def test_qt_event_loop_block_is_detected(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication

        module = _load_probe_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src" / "truba_gui").mkdir(parents=True)
            session = module.PerformanceSession(root, interval_ms=20, slow_ms=30)
            session.start()
            app = QApplication.instance() or QApplication([])
            session.attach_to_app(app)
            QTimer.singleShot(40, lambda: time.sleep(0.12))
            QTimer.singleShot(260, app.quit)

            app.exec()
            session.finish(0)

            events = [
                json.loads(line)
                for line in session.report_path.read_text(encoding="utf-8").splitlines()
            ]
            delays = [event for event in events if event["event"] == "event_loop_delay"]
            self.assertTrue(delays)
            self.assertGreaterEqual(delays[0]["delay_ms"], 80)

    def test_slow_event_loop_tick_is_recorded(self):
        module = _load_probe_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src" / "truba_gui").mkdir(parents=True)
            session = module.PerformanceSession(
                root,
                interval_ms=100,
                slow_ms=200,
                now=lambda: 10.0,
            )
            session._expected_tick = 10.1

            delay_ms = session.measure_tick(10.35)

            self.assertAlmostEqual(delay_ms, 250.0)
            events = [
                json.loads(line)
                for line in session.report_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(events[0]["event"], "event_loop_delay")
            self.assertEqual(events[0]["delay_ms"], 250.0)

    def test_fast_event_loop_tick_does_not_write_delay(self):
        module = _load_probe_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src" / "truba_gui").mkdir(parents=True)
            session = module.PerformanceSession(
                root,
                interval_ms=100,
                slow_ms=200,
                now=lambda: 10.0,
            )
            session._expected_tick = 10.1

            delay_ms = session.measure_tick(10.15)

            self.assertAlmostEqual(delay_ms, 50.0)
            self.assertFalse(session.report_path.exists())


if __name__ == "__main__":
    unittest.main()
