from __future__ import annotations

import stat as pystat
from typing import List, Tuple

from truba_gui.services.files_base import FilesBackend, RemoteEntry
from truba_gui.ssh.client import SSHClientWrapper

class SSHFilesBackend(FilesBackend):
    def __init__(self, ssh: SSHClientWrapper):
        if not ssh.sftp:
            raise RuntimeError("SFTP not available")
        self.ssh = ssh

    def listdir(self, remote_dir: str) -> List[str]:
        return self.ssh.sftp.listdir(remote_dir)

    def listdir_entries(self, remote_dir: str) -> List[RemoteEntry]:
        entries: List[RemoteEntry] = []
        for attr in self.ssh.sftp.listdir_attr(remote_dir):
            name = getattr(attr, "filename", "") or ""
            path = remote_dir.rstrip("/") + "/" + name
            mode = getattr(attr, "st_mode", 0) or 0
            is_dir = pystat.S_ISDIR(mode)
            size = int(getattr(attr, "st_size", 0) or 0)
            mtime = int(getattr(attr, "st_mtime", 0) or 0)
            entries.append(RemoteEntry(
                name=name, path=path, is_dir=is_dir, size=size, mtime=mtime, mode=mode
            ))
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def read_text(self, remote_path: str) -> str:
        with self.ssh.sftp.open(remote_path, "rb") as f:
            data = f.read()
        return data.decode("utf-8", errors="replace")

    def write_text(self, remote_path: str, text: str) -> None:
        with self.ssh.sftp.open(remote_path, "wb") as f:
            f.write(text.encode("utf-8"))

    def stat(self, remote_path: str) -> Tuple[int, int]:
        st = self.ssh.sftp.stat(remote_path)
        return int(getattr(st, "st_size", 0) or 0), int(getattr(st, "st_mtime", 0) or 0)

    def download(self, remote_path: str, local_path: str) -> None:
        self.ssh.sftp.get(remote_path, local_path)

    def upload(self, local_path: str, remote_path: str) -> None:
        self.ssh.sftp.put(local_path, remote_path)
