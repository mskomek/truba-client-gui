import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath("src"))

from PySide6.QtWidgets import QApplication, QMessageBox

from truba_gui.ui.widgets.editor_widget import EditorWidget


class _FakeFiles:
    def __init__(self):
        self.data = {}

    def read_text(self, remote_path: str) -> str:
        return self.data[remote_path]

    def write_text(self, remote_path: str, text: str) -> None:
        self.data[remote_path] = text


class _FakeSlurm:
    def __init__(self, out: str):
        self.out = out
        self.calls = []

    def sbatch(self, script_path: str) -> str:
        self.calls.append(script_path)
        return self.out


class EditorFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.files = _FakeFiles()
        self.slurm = _FakeSlurm("Submitted batch job 12345")
        self.w = EditorWidget()
        self.w.set_session({"files": self.files, "slurm": self.slurm})

        self._orig_question = QMessageBox.question
        self._orig_info = QMessageBox.information
        self._orig_warn = QMessageBox.warning
        self._orig_critical = QMessageBox.critical
        QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
        QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
        QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)

    def tearDown(self):
        QMessageBox.question = self._orig_question
        QMessageBox.information = self._orig_info
        QMessageBox.warning = self._orig_warn
        QMessageBox.critical = self._orig_critical
        self.w.deleteLater()

    def test_save_submit_emits_job_signal(self):
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        got = []
        self.w.script_submitted.connect(lambda jid, path: got.append((jid, path)))
        self.w.path_in.setText("/arf/scratch/user/a.slurm")
        self.w.text.setPlainText("#!/bin/bash\n#SBATCH -p orfoz\necho ok\n")

        self.w.save_path(force_submit=True)

        self.assertEqual(self.files.data["/arf/scratch/user/a.slurm"].strip().splitlines()[0], "#!/bin/bash")
        self.assertEqual(self.slurm.calls, ["/arf/scratch/user/a.slurm"])
        self.assertEqual(got, [("12345", "/arf/scratch/user/a.slurm")])

    def test_save_non_slurm_does_not_submit(self):
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        self.w.path_in.setText("/arf/scratch/user/readme.txt")
        self.w.text.setPlainText("hello")

        self.w.save_path()

        self.assertEqual(self.files.data["/arf/scratch/user/readme.txt"], "hello")
        self.assertEqual(self.slurm.calls, [])

    def test_validation_can_block_save(self):
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
        self.w.path_in.setText("/arf/scratch/user/bad.slurm")
        self.w.text.setPlainText("echo no directives")

        self.w.save_path(force_submit=True)

        self.assertNotIn("/arf/scratch/user/bad.slurm", self.files.data)
        self.assertEqual(self.slurm.calls, [])


if __name__ == "__main__":
    unittest.main()
