from __future__ import annotations

import shiboken6

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QLineEdit, QMessageBox
)

from truba_gui.core.i18n import t
from truba_gui.services.x11_system_ssh import build_x11_launch
from truba_gui.services.xserver_manager import ensure_x_server_running


class X11Widget(QWidget):
    """X11 forwarding test + remote GUI launcher.

    İstenen davranış:
    - X11 forwarding seçiliyken 'xclock' gönderildiğinde **yerel X server** üzerinde
      ayrı bir pencere açılır.
    - TrubaGUI içinde yeni sekme açılmaz.

    Bu widget sadece komutu başlatır ve temel log gösterir.
    """

    def __init__(self):
        super().__init__()
        self.session = None
        # log callback used by xserver_manager (expects callable(str) -> None)
        # Keep it simple: append to the status label.
        self._log = self._log_to_label

        self.lbl = QLabel(
            "X11: Yerel X server (VcXsrv/Xming) açık olmalı.\n"
            "Test: xclock (ayrı pencere açılmalı)."
        )
        self.lbl.setWordWrap(True)

        # command input
        self.cmd_in = QLineEdit()
        self.cmd_in.setPlaceholderText("Örn: xclock  |  matlab  |  xterm")
        self.cmd_in.setText("xclock")

        self.btn_test = QPushButton("Test: xclock")
        self.btn_test.clicked.connect(self.run_xclock)

        self.btn_run = QPushButton("Çalıştır (X11)")
        self.btn_run.clicked.connect(self.run_custom)
        self.cmd_in.returnPressed.connect(self.run_custom)

        row = QHBoxLayout()
        row.addWidget(self.cmd_in)
        row.addWidget(self.btn_run)

        lay = QVBoxLayout(self)
        lay.addWidget(self.lbl)
        lay.addLayout(row)
        lay.addWidget(self.btn_test)
        lay.addStretch(1)

        # keep refs (avoid GC)
        self._procs: list[QProcess] = []

    def set_session(self, session):
        self.session = session

    def shutdown_external_processes(self) -> None:
        """Terminate background plink/ssh processes launched from this tab."""
        for p in list(getattr(self, "_procs", [])):
            try:
                if p.state() != QProcess.ProcessState.NotRunning:
                    p.terminate()
                    p.waitForFinished(1000)
            except Exception:
                pass
        try:
            self._procs.clear()
        except Exception:
            pass

    def _log_to_label(self, msg: str) -> None:
        """Append short diagnostic messages to the label."""
        msg = (msg or "").strip()
        if not msg:
            return
        current = self.lbl.text()
        new_text = (current + "\n" + msg).strip()
        if len(new_text) > 2000:
            new_text = new_text[-2000:]
        self.lbl.setText(new_text)

    def _ensure_ready(self) -> bool:
        if not self.session or not self.session.get("connected"):
            self.lbl.setText(t("common.no_connection"))
            return False
        cfg = self.session["cfg"]
        if not getattr(cfg, "x11_forwarding", False):
            self.lbl.setText("X11 forwarding kapalı. Login ekranında X11'i aç.")
            return False
        # Ensure a local X server exists (standalone: download from GitHub releases if missing).
        if not ensure_x_server_running(log=self._log, parent=self, allow_download=True):
            self.lbl.setText("Yerel X server bulunamadı. X11 pencereleri için VcXsrv indirilmeli/çalışmalı.")
            return False

        return True

    def run_xclock(self):
        self.cmd_in.setText("xclock")
        self.run_custom()

    def run_custom(self):
        if not self._ensure_ready():
            return

        cfg = self.session["cfg"]
        remote_cmd = self.cmd_in.text().strip() or "xclock"

        # Qt/Matlab gibi GUI'ler için sık görülen X11 paylaşımlı bellek sorunu:
        # Kullanıcı isterse komutu kendisi bash -lc ile yazabilir.
        launch = build_x11_launch(
            host=cfg.host,
            port=cfg.port,
            user=cfg.username,
            remote_cmd=remote_cmd,
            trusted=True,
            key_path=(cfg.key_path or None),
        )

        if not launch:
            QMessageBox.critical(
                self,
                "X11",
                "Yerel 'ssh' veya 'plink' bulunamadı.\n"
                "Windows: PuTTY (plink) veya OpenSSH kurup PATH'e ekle.",
            )
            return

        # Parola ile arka planda çalıştırma güvenilir değil.
        # Key yoksa kullanıcıya uyar.
        if (not (cfg.key_path or "").strip()) and (cfg.password or "").strip():
            QMessageBox.warning(
                self,
                "X11",
                "Bu projede X11 komutları arka planda başlatılır.\n"
                "Parola etkileşimi arka planda sorun çıkarabilir.\n"
                "Öneri: SSH key/agent kullan.",
            )

        proc = QProcess(self)
        proc.setProgram(launch.program)
        proc.setArguments(launch.args)

        # stdout/stderr'i label'a basitçe yazalım (GUI açılırken genelde boş olur)
        proc.readyReadStandardOutput.connect(lambda: self._append(proc, "out"))
        proc.readyReadStandardError.connect(lambda: self._append(proc, "err"))
        proc.finished.connect(lambda code, status: self._finished(proc, code, status))

        # X11 penceresinin *ayrı pencere* olarak açılması, yerel X server'a bağlı.
        # QProcess sadece ssh/plink sürecini başlatır.
        self._procs.append(proc)
        proc.start()

        cmd_show = " ".join([launch.program] + launch.args)
        self.lbl.setText(
            "Başlatıldı (X11):\n"
            f"{cmd_show}\n\n"
            "Beklenen: xclock/matlab penceresi Windows'ta ayrı açılır.\n"
            "Eğer açılmıyorsa: X server açık mı? (VcXsrv/Xming)  |  echo $DISPLAY"
        )

    def _append(self, proc: QProcess, which: str):
        if not shiboken6.isValid(self.lbl):
            return
        if which == "out":
            data = bytes(proc.readAllStandardOutput()).decode(errors="ignore")
        else:
            data = bytes(proc.readAllStandardError()).decode(errors="ignore")
        data = data.strip()
        if not data:
            return
        # label çok büyümesin
        current = self.lbl.text()
        new_text = (current + "\n" + data).strip()
        if len(new_text) > 2000:
            new_text = new_text[-2000:]
        self.lbl.setText(new_text)

    def _finished(self, proc: QProcess, code: int, status: QProcess.ExitStatus):
        if not shiboken6.isValid(self.lbl):
            return
        # proc listesinde kalsın ama UI'ya bilgi ver
        st = "normal" if status == QProcess.ExitStatus.NormalExit else "crash"
        current = self.lbl.text()
        self.lbl.setText((current + f"\n\n[SSH/PLINK bitti] code={code}, status={st}").strip())