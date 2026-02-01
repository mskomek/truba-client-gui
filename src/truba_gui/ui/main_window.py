from PySide6.QtWidgets import QMainWindow, QTabWidget

from truba_gui.core.i18n import t
from .widgets.login_widget import LoginWidget
from .widgets.jobs_outputs_widget import JobsOutputsWidget
from .widgets.directories_widget import DirectoriesWidget
from .widgets.editor_widget import EditorWidget
from .widgets.x11_widget import X11Widget
from .widgets.logs_widget import LogsWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(t("app.title"))

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.login = LoginWidget()
        self.jobs_outputs = JobsOutputsWidget()
        self.directories = DirectoriesWidget()
        self.editor = EditorWidget()
        self.x11 = X11Widget()
        self.logs = LogsWidget()

        self.tabs.addTab(self.login, t("tabs.login"))
        self.tabs.addTab(self.jobs_outputs, t("tabs.jobs_outputs"))
        self.tabs.addTab(self.directories, t("tabs.directories"))
        self.tabs.addTab(self.editor, t("tabs.editor"))
        self.tabs.addTab(self.x11, t("tabs.x11"))
        self.tabs.addTab(self.logs, t("tabs.logs") if t("tabs.logs") != "[tabs.logs]" else "Logs")

        self.login.session_changed.connect(self.on_session_changed)

        # Job completion monitor
        from PySide6.QtCore import QTimer
        self.job_timer = QTimer(self)
        self.job_timer.setInterval(5000)
        self.job_timer.timeout.connect(self._poll_jobs)
        self._last_job_ids = set()

        self.jobs_outputs.request_show_directories.connect(self.show_directories)
        self.directories.open_in_editor.connect(self.open_in_editor)

    def on_session_changed(self, session):
        self.jobs_outputs.set_session(session)
        self.directories.set_session(session)
        self.editor.set_session(session)
        self.x11.set_session(session)

    def show_directories(self):
        idx = self.tabs.indexOf(self.directories)
        if idx >= 0:
            self.tabs.setCurrentIndex(idx)

    def open_in_editor(self, path: str, content: str):
        self.editor.open_file(path, content)
        idx = self.tabs.indexOf(self.editor)
        if idx >= 0:
            self.tabs.setCurrentIndex(idx)

    def _poll_jobs(self):
        # Called every 5s when connected; logs finished jobs to login console
        session = getattr(self, "_session", None)
        if not session or not session.get("connected"):
            return
        ssh = session.get("ssh")
        cfg = session.get("cfg")
        if not ssh or not cfg:
            return
        try:
            # Get active job ids
            code, out, err = ssh.run(f'squeue -h -u {cfg.username} -o "%A"')
            job_ids = set([ln.strip() for ln in out.splitlines() if ln.strip().isdigit()])
        except Exception:
            return
        # detect finished
        finished = self._last_job_ids - job_ids
        for jid in sorted(finished):
            msg = t("login.job_finished")
            if msg.startswith("["):
                msg = "İş bitti: {jobid}"
            self.login.append_console(msg.format(jobid=jid))
        self._last_job_ids = job_ids

    def closeEvent(self, event):
        """Gracefully stop background helper processes on app exit.

        Controlled by Login settings:
        - close_vcxsrv_on_exit
        - close_x11_procs_on_exit
        """
        try:
            if hasattr(self, "login") and self.login:
                self.login.shutdown_external_processes()
        except Exception:
            pass
        try:
            if hasattr(self, "x11") and self.x11:
                # optional: kill X11 widget processes too
                if hasattr(self.x11, "shutdown_external_processes"):
                    self.x11.shutdown_external_processes()
        except Exception:
            pass
        super().closeEvent(event)
