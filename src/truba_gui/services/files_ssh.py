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

    def remove(self, remote_path: str, recursive: bool = False) -> None:
        # Use shell rm to support recursive deletes reliably.
        # remote_path is user-provided via UI; quote defensively.
        import shlex
        q = shlex.quote(remote_path)
        cmd = f"rm {'-rf' if recursive else '-f'} {q}"
        code, _, err = self.ssh.run(cmd)
        if code != 0:
            raise RuntimeError(err.strip() or f"rm failed (exit={code})")

    def rename(self, remote_path: str, new_remote_path: str) -> None:
        # Prefer SFTP rename (atomic on many servers)
        self.ssh.sftp.rename(remote_path, new_remote_path)

    def mkdir(self, remote_dir: str) -> None:
        import shlex
        q = shlex.quote(remote_dir)
        code, _, err = self.ssh.run(f"mkdir -p {q}")
        if code != 0:
            raise RuntimeError(err.strip() or f"mkdir failed (exit={code})")

    def copy(self, src_remote_path: str, dst_remote_path: str, recursive: bool = False) -> None:
        import shlex
        s = shlex.quote(src_remote_path)
        d = shlex.quote(dst_remote_path)
        cmd = f"cp {'-r' if recursive else ''} {s} {d}".strip()
        code, _, err = self.ssh.run(cmd)
        if code != 0:
            raise RuntimeError(err.strip() or f"cp failed (exit={code})")

    def move(self, src_remote_path: str, dst_remote_path: str) -> None:
        import shlex
        s = shlex.quote(src_remote_path)
        d = shlex.quote(dst_remote_path)
        code, _, err = self.ssh.run(f"mv {s} {d}")
        if code != 0:
            raise RuntimeError(err.strip() or f"mv failed (exit={code})")
