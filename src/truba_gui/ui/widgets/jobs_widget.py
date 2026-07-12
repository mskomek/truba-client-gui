from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QTextEdit, QLineEdit, QHBoxLayout
from truba_gui.core.i18n import t
from truba_gui.core.history import append_event

class JobsWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.session = None

        self.out = QTextEdit()
        self.out.setReadOnly(True)

        self.btn_refresh = QPushButton(t("jobs.refresh"))
        self.btn_refresh.setText(t("jobs.refresh"))
        self.btn_refresh.clicked.connect(self.refresh)

        self.cancel_id = QLineEdit()
        self.cancel_id.setPlaceholderText(t("jobs.job_id"))
        self.btn_cancel = QPushButton(t("jobs.cancel"))
        self.btn_cancel.clicked.connect(self.cancel)

        row = QHBoxLayout()
        row.addWidget(self.btn_refresh)
        row.addStretch(1)
        row.addWidget(self.cancel_id)
        row.addWidget(self.btn_cancel)

        lay = QVBoxLayout(self)
        lay.addLayout(row)
        lay.addWidget(self.out)

    def set_session(self, session):
        self.session = session
        self.out.setPlainText("")

    def refresh(self):
        if not self.session or not self.session.get("slurm"):
            self.out.setPlainText(t("common.no_connection"))
            return
        user = self.session["cfg"].username
        text = self.session["slurm"].squeue(user)
        self.out.setPlainText(text)
        append_event({"type": "squeue", "user": user})

    def cancel(self):
        if not self.session or not self.session.get("slurm"):
            return
        jobid = self.cancel_id.text().strip()
        if not jobid:
            return
        res = self.session["slurm"].scancel(jobid)
        self.out.append("\n" + res)
        append_event({"type": "scancel", "jobid": jobid})
