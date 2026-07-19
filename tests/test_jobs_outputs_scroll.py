from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMainWindow, QTextEdit
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from truba_gui.ui.widgets.jobs_outputs_widget import (
    JobsOutputsWidget,
    _NavigableTextEdit,
)


class JobsOutputsScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.editor = _NavigableTextEdit()
        self.editor.setLineWrapMode(QTextEdit.NoWrap)
        self.editor.resize(320, 120)
        self.editor.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.editor.close()
        self.editor.deleteLater()

    @staticmethod
    def _lines(count: int) -> str:
        return "\n".join(f"line {index}" for index in range(count))

    def test_live_follow_scrolls_to_latest_line(self) -> None:
        JobsOutputsWidget._set_live_text(
            self.editor,
            self._lines(200),
            follow_latest=True,
        )

        self.assertEqual(
            self.editor.textCursor().position(),
            len(self.editor.toPlainText()),
        )
        self.app.processEvents()

        scrollbar = self.editor.verticalScrollBar()
        self.assertEqual(scrollbar.value(), scrollbar.maximum())

    def test_refresh_without_follow_preserves_scroll_position(self) -> None:
        self.editor.setPlainText(self._lines(200))
        self.app.processEvents()
        scrollbar = self.editor.verticalScrollBar()
        scrollbar.setValue(25)

        JobsOutputsWidget._set_live_text(
            self.editor,
            self._lines(220),
            follow_latest=False,
        )
        self.app.processEvents()

        self.assertEqual(scrollbar.value(), 25)
        self.assertLess(scrollbar.value(), scrollbar.maximum())

    def test_refresh_preserves_horizontal_position_when_following_latest(self) -> None:
        long_line = "x" * 240
        self.editor.setPlainText("\n".join(f"{long_line}{index}" for index in range(200)))
        self.app.processEvents()
        vertical_scrollbar = self.editor.verticalScrollBar()
        horizontal_scrollbar = self.editor.horizontalScrollBar()
        vertical_scrollbar.setValue(vertical_scrollbar.maximum())
        horizontal_scrollbar.setValue(40)
        self.assertTrue(JobsOutputsWidget._is_scrolled_to_bottom(self.editor))

        JobsOutputsWidget._set_live_text(
            self.editor,
            "\n".join(f"{long_line}{index}" for index in range(220)),
            follow_latest=True,
        )
        self.app.processEvents()

        self.assertEqual(vertical_scrollbar.value(), vertical_scrollbar.maximum())
        self.assertEqual(horizontal_scrollbar.value(), 40)

    def test_bottom_state_controls_follow_per_refresh(self) -> None:
        self.editor.setPlainText(self._lines(200))
        self.app.processEvents()
        scrollbar = self.editor.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.assertTrue(JobsOutputsWidget._is_scrolled_to_bottom(self.editor))

        JobsOutputsWidget._set_live_text(
            self.editor,
            self._lines(220),
            follow_latest=JobsOutputsWidget._is_scrolled_to_bottom(self.editor),
        )
        self.app.processEvents()
        self.assertEqual(scrollbar.value(), scrollbar.maximum())

        scrollbar.setValue(max(0, scrollbar.maximum() - 20))
        self.assertFalse(JobsOutputsWidget._is_scrolled_to_bottom(self.editor))
        previous = scrollbar.value()
        JobsOutputsWidget._set_live_text(
            self.editor,
            self._lines(230),
            follow_latest=JobsOutputsWidget._is_scrolled_to_bottom(self.editor),
        )
        self.app.processEvents()
        self.assertEqual(scrollbar.value(), previous)

    def test_page_navigation_and_end_update_scroll_position(self) -> None:
        self.editor.setPlainText(self._lines(300))
        self.editor.setFocus()
        self.app.processEvents()
        scrollbar = self.editor.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        QTest.keyClick(self.editor, Qt.Key.Key_PageUp)
        self.app.processEvents()
        self.assertLess(scrollbar.value(), scrollbar.maximum())

        before = scrollbar.value()
        QTest.keyClick(self.editor, Qt.Key.Key_PageDown)
        self.app.processEvents()
        self.assertGreaterEqual(scrollbar.value(), before)

        QTest.keyClick(self.editor, Qt.Key.Key_End)
        self.app.processEvents()
        self.assertEqual(scrollbar.value(), scrollbar.maximum())

    def test_pause_changes_scrolling_without_stopping_refresh_timer(self) -> None:
        widget = JobsOutputsWidget()
        widget.session = {"connected": True}
        widget.active_out = "/tmp/output.log"
        widget.section_tabs.setCurrentWidget(widget.outputs_tab)
        widget._live_timer.start()

        widget._toggle_tail_pause()

        self.assertTrue(widget._tail_paused)
        self.assertTrue(widget._live_timer.isActive())
        self.assertFalse(widget.btn_tail_pause.isVisible())
        widget.shutdown()
        widget.deleteLater()

    @staticmethod
    def _run_async_immediately(_key, fn, on_success, **_kwargs) -> bool:
        on_success(fn())
        return True

    def _assert_fake_tail_window_stream(
        self,
        follower,
        paths: tuple[str, ...],
    ) -> None:
        class FakeFiles:
            content: dict[str, str] = {}

            @classmethod
            def read_text(cls, path: str) -> str:
                return cls.content[path]

        def make_lines(start: int, stop: int) -> str:
            return "\n".join(
                f"{'x' * 240} line {index}"
                for index in range(start, stop)
            )

        FakeFiles.content = {path: make_lines(0, 220) for path in paths}
        follower._start_async = self._run_async_immediately
        follower.set_session({"connected": True, "files": FakeFiles(), "ssh": None})
        self.app.processEvents()

        scrollbars = []
        for path in paths:
            output = follower.txt_out if path == follower.active_out else follower.txt_err
            vertical = output.verticalScrollBar()
            horizontal = output.horizontalScrollBar()
            vertical.setValue(vertical.maximum())
            horizontal.setValue(35)
            scrollbars.append((path, output, vertical, horizontal))

        for path in paths:
            FakeFiles.content[path] = make_lines(0, 221)
        follower._poll_live()
        self.app.processEvents()

        for path, _output, vertical, horizontal in scrollbars:
            self.assertEqual(vertical.value(), vertical.maximum(), path)
            self.assertEqual(horizontal.value(), 35, path)

        previous_positions = {}
        for path, _output, vertical, _horizontal in scrollbars:
            vertical.setValue(max(0, vertical.maximum() - 20))
            previous_positions[path] = vertical.value()

        for path in paths:
            FakeFiles.content[path] = make_lines(0, 240)
        follower._poll_live()
        self.app.processEvents()

        for path, _output, vertical, horizontal in scrollbars:
            self.assertEqual(vertical.value(), previous_positions[path], path)
            self.assertEqual(horizontal.value(), 35, path)

    def test_all_follow_windows_preserve_fake_tail_scroll_positions(self) -> None:
        cases = (
            ("output1", lambda widget: widget.open_in_output_window(0, "/tmp/out.log"), ("/tmp/out.log",)),
            ("output2", lambda widget: widget.open_in_output_window(1, "/tmp/err.log"), ("/tmp/err.log",)),
            (
                "combined",
                lambda widget: widget.open_output_pair_window("/tmp/out.log", "/tmp/err.log"),
                ("/tmp/out.log", "/tmp/err.log"),
            ),
            (
                "single",
                lambda widget: widget.open_file_follow_window("/tmp/out.log"),
                ("/tmp/out.log",),
            ),
        )

        for name, open_window, paths in cases:
            with self.subTest(window=name):
                widget = JobsOutputsWidget()
                try:
                    result = open_window(widget)
                    window = result or widget._follow_windows[-1]
                    self.assertIsInstance(window, QMainWindow)
                    self.assertTrue(window.isWindow())
                    self._assert_fake_tail_window_stream(
                        window.centralWidget(),
                        paths,
                    )
                finally:
                    widget.shutdown()
                    widget.deleteLater()
                    self.app.processEvents()

    def test_ssh_poll_requests_last_200_lines_for_both_outputs(self) -> None:
        class FakeSSH:
            def __init__(self) -> None:
                self.commands = []

            def run(self, command, log_output=False):
                self.commands.append((command, log_output))
                return 0, f"content for {command}", ""

        ssh = FakeSSH()
        widget = JobsOutputsWidget()
        widget.section_tabs.setCurrentWidget(widget.outputs_tab)
        widget.session = {"connected": True, "files": object(), "ssh": ssh}
        widget.active_out = "/tmp/output file.log"
        widget.active_err = "/tmp/error file.log"
        widget._start_async = self._run_async_immediately

        widget._poll_live()
        self.app.processEvents()

        self.assertEqual(len(ssh.commands), 2)
        self.assertTrue(all("tail -n 200 --" in command for command, _ in ssh.commands))
        self.assertTrue(all(log_output is False for _, log_output in ssh.commands))
        self.assertIn("content for", widget.txt_out.toPlainText())
        self.assertIn("content for", widget.txt_err.toPlainText())
        widget.shutdown()
        widget.deleteLater()

    def test_file_fallback_displays_only_last_200_lines(self) -> None:
        class FakeFiles:
            @staticmethod
            def read_text(_path):
                return "\n".join(f"line {index}" for index in range(250))

        widget = JobsOutputsWidget()
        widget.section_tabs.setCurrentWidget(widget.outputs_tab)
        widget.session = {"connected": True, "files": FakeFiles()}
        widget.active_out = "/tmp/output.log"
        widget._start_async = self._run_async_immediately

        widget._poll_live()
        self.app.processEvents()

        lines = widget.txt_out.toPlainText().splitlines()
        self.assertEqual(len(lines), 200)
        self.assertEqual(lines[0], "line 50")
        self.assertNotIn("line 49", lines)
        self.assertEqual(lines[-1], "line 249")
        widget.shutdown()
        widget.deleteLater()

    def test_follow_window_output1_then_assigns_output2(self) -> None:
        widget = JobsOutputsWidget()
        try:
            widget.open_in_output_window(0, "/tmp/stdout.log")
            self.app.processEvents()

            self.assertEqual(len(widget._follow_windows), 1)
            window = widget._follow_windows[0]
            self.assertIsInstance(window, QMainWindow)
            self.assertTrue(window.isWindow())
            self.assertIsNone(window.parentWidget())
            target_id, _label = widget._output_target_choices()[0]
            follower = widget._follow_targets[target_id]
            self.assertEqual(follower.active_out, "/tmp/stdout.log")
            self.assertEqual(follower.active_err, "")
            self.assertTrue(follower.err_box.isVisible())

            widget.open_in_existing_follower(
                target_id,
                1,
                "/tmp/stderr.log",
            )

            self.assertEqual(follower.active_out, "/tmp/stdout.log")
            self.assertEqual(follower.active_err, "/tmp/stderr.log")
            self.assertEqual(follower.path_err.text(), "/tmp/stderr.log")
        finally:
            widget.shutdown()
            widget.deleteLater()
            self.app.processEvents()

    def test_follow_tab_output2_then_assigns_output1_and_is_closable(self) -> None:
        widget = JobsOutputsWidget()
        try:
            self.assertEqual(widget.section_tabs.count(), 3)
            widget.open_in_output_tab(1, "/tmp/stderr.log")
            self.app.processEvents()

            self.assertEqual(widget.section_tabs.count(), 4)
            target_id, _label = widget._output_target_choices()[0]
            follower = widget._follow_targets[target_id]
            self.assertEqual(follower.active_out, "")
            self.assertEqual(follower.active_err, "/tmp/stderr.log")
            self.assertFalse(follower.out_box.isHidden())

            widget.open_in_existing_follower(
                target_id,
                0,
                "/tmp/stdout.log",
            )

            self.assertEqual(follower.active_out, "/tmp/stdout.log")
            self.assertEqual(follower.active_err, "/tmp/stderr.log")
            self.assertEqual(follower.path_out.text(), "/tmp/stdout.log")

            widget._close_follow_tab(0)
            self.assertEqual(widget.section_tabs.count(), 4)
            widget._close_follow_tab(3)
            self.assertEqual(widget.section_tabs.count(), 3)
            self.assertEqual(widget._output_target_choices(), [])
        finally:
            widget.shutdown()
            widget.deleteLater()
            self.app.processEvents()

    def test_main_output_address_enter_switches_follow_target(self) -> None:
        widget = JobsOutputsWidget()
        try:
            self.assertFalse(widget.path_out.isReadOnly())
            self.assertFalse(widget.path_err.isReadOnly())
            widget.path_out.setText("  /tmp/other-output.log  ")

            widget.path_out.returnPressed.emit()

            self.assertEqual(widget.active_out, "/tmp/other-output.log")
            self.assertEqual(widget.path_out.text(), "/tmp/other-output.log")
            self.assertEqual(widget.section_tabs.currentWidget(), widget.outputs_tab)
        finally:
            widget.shutdown()
            widget.deleteLater()
            self.app.processEvents()

    def test_single_file_follow_window_address_accepts_typing_and_enter(self) -> None:
        widget = JobsOutputsWidget()
        try:
            window = widget.open_file_follow_window("/tmp/stdout.log")
            self.assertIsNotNone(window)
            follower = window.centralWidget()
            self.assertFalse(follower.path_out.isReadOnly())
            follower.path_out.setFocus()
            follower.path_out.selectAll()

            QTest.keyClicks(follower.path_out, "/tmp/reassigned.log")
            self.app.processEvents()

            self.assertEqual(follower.path_out.text(), "/tmp/reassigned.log")

            QTest.keyClick(follower.path_out, Qt.Key.Key_Return)
            self.app.processEvents()

            self.assertEqual(follower.active_out, "/tmp/reassigned.log")
            self.assertEqual(follower.path_out.text(), "/tmp/reassigned.log")
        finally:
            widget.shutdown()
            widget.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
