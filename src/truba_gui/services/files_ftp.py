from __future__ import annotations

import calendar
import os
import posixpath
import stat as pystat
import tempfile
from ftplib import FTP, error_perm
from typing import List, Tuple

from truba_gui.services.files_base import FilesBackend, RemoteEntry


def _norm(path: str) -> str:
    value = (path or "/").replace("\\", "/").strip() or "/"
    if not value.startswith("/"):
        value = "/" + value
    value = posixpath.normpath(value)
    return "/" if value in {"", "."} else value


def _parse_modify(value: str) -> int:
    text = (value or "").strip()
    if len(text) < 14:
        return 0
    try:
        parts = (
            int(text[0:4]),
            int(text[4:6]),
            int(text[6:8]),
            int(text[8:10]),
            int(text[10:12]),
            int(text[12:14]),
        )
        return int(calendar.timegm(parts + (0, 0, 0)))
    except Exception:
        return 0


class FTPFilesBackend(FilesBackend):
    """Plain FTP implementation of the app's file-transfer backend."""

    supports_parallel_transfers = False

    def __init__(
        self,
        host: str,
        *,
        port: int = 21,
        username: str = "",
        password: str = "",
        timeout: float = 20.0,
    ) -> None:
        self._host = host
        self._port = int(port)
        self._username = username or "anonymous"
        self._password = password or ""
        self._timeout = float(timeout)
        self.ftp = FTP()
        self.ftp.connect(self._host, self._port, timeout=self._timeout)
        self.ftp.login(self._username, self._password)
        self.ftp.voidcmd("TYPE I")
        try:
            self.ftp.set_pasv(True)
        except Exception:
            pass

    def open_transfer_backend(self) -> "FTPFilesBackend":
        return FTPFilesBackend(
            self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            timeout=self._timeout,
        )

    def close(self) -> None:
        try:
            self.ftp.quit()
        except Exception:
            try:
                self.ftp.close()
            except Exception:
                pass

    def listdir(self, remote_dir: str) -> List[str]:
        return [entry.name for entry in self.listdir_entries(remote_dir)]

    def listdir_entries(self, remote_dir: str) -> List[RemoteEntry]:
        remote_dir = _norm(remote_dir)
        entries: list[RemoteEntry] = []
        try:
            rows = list(self.ftp.mlsd(remote_dir))
            for name, facts in rows:
                if name in {"", ".", ".."}:
                    continue
                kind = str(facts.get("type", "")).lower()
                is_dir = kind in {"dir", "cdir", "pdir"}
                path = _norm(posixpath.join(remote_dir, name))
                size = 0 if is_dir else int(facts.get("size") or 0)
                mtime = _parse_modify(str(facts.get("modify") or ""))
                mode = pystat.S_IFDIR if is_dir else pystat.S_IFREG
                entries.append(
                    RemoteEntry(
                        name=name,
                        path=path,
                        is_dir=is_dir,
                        size=size,
                        mtime=mtime,
                        mode=mode,
                    )
                )
        except Exception:
            entries = self._listdir_entries_fallback(remote_dir)
        entries.sort(key=lambda item: (not item.is_dir, item.name.lower()))
        return entries

    def _listdir_entries_fallback(self, remote_dir: str) -> list[RemoteEntry]:
        names = self.ftp.nlst(remote_dir)
        entries: list[RemoteEntry] = []
        for item in names:
            name = posixpath.basename(item.rstrip("/"))
            if name in {"", ".", ".."}:
                continue
            path = _norm(item if item.startswith("/") else posixpath.join(remote_dir, item))
            is_dir = self.is_dir(path)
            try:
                size, mtime = self.stat(path)
            except Exception:
                size, mtime = 0, 0
            entries.append(
                RemoteEntry(
                    name=name,
                    path=path,
                    is_dir=is_dir,
                    size=0 if is_dir else size,
                    mtime=mtime,
                    mode=pystat.S_IFDIR if is_dir else pystat.S_IFREG,
                )
            )
        return entries

    def read_text(self, remote_path: str) -> str:
        chunks: list[bytes] = []
        self.ftp.retrbinary(f"RETR {_norm(remote_path)}", chunks.append)
        return b"".join(chunks).decode("utf-8", errors="replace")

    def write_text(self, remote_path: str, text: str) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(text.encode("utf-8"))
            tmp_path = tmp.name
        try:
            self.upload(tmp_path, remote_path)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def stat(self, remote_path: str) -> Tuple[int, int]:
        remote_path = _norm(remote_path)
        try:
            self.ftp.voidcmd("TYPE I")
            size = 0 if self.is_dir(remote_path) else int(self.ftp.size(remote_path) or 0)
        except Exception:
            size = 0
        mtime = 0
        try:
            resp = self.ftp.sendcmd(f"MDTM {remote_path}")
            if resp.startswith("213"):
                mtime = _parse_modify(resp[4:].strip())
        except Exception:
            pass
        if size == 0 and not self.exists(remote_path):
            raise FileNotFoundError(remote_path)
        return size, mtime

    def download(self, remote_path: str, local_path: str, progress_cb=None) -> None:
        remote_path = _norm(remote_path)
        self.ftp.voidcmd("TYPE I")
        remote_size, _ = self.stat(remote_path)
        local_size = 0
        try:
            local_size = os.path.getsize(local_path)
        except Exception:
            local_size = 0
        if local_size == remote_size and remote_size > 0:
            if progress_cb is not None:
                progress_cb(remote_size, remote_size)
            return
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        mode = "ab" if 0 < local_size < remote_size else "wb"
        transferred = local_size if mode == "ab" else 0

        def on_chunk(chunk: bytes) -> None:
            nonlocal transferred
            handle.write(chunk)
            transferred += len(chunk)
            if progress_cb is not None:
                progress_cb(transferred, remote_size)

        with open(local_path, mode) as handle:
            self.ftp.retrbinary(
                f"RETR {remote_path}",
                on_chunk,
                rest=local_size if mode == "ab" else None,
            )

    def upload(self, local_path: str, remote_path: str, progress_cb=None) -> None:
        remote_path = _norm(remote_path)
        self.ftp.voidcmd("TYPE I")
        self._ensure_parent_dirs(remote_path)
        local_size = os.path.getsize(local_path)
        remote_size = 0
        try:
            remote_size, _ = self.stat(remote_path)
        except Exception:
            remote_size = 0
        if remote_size == local_size and local_size > 0:
            if progress_cb is not None:
                progress_cb(local_size, local_size)
            return
        command = "APPE" if 0 < remote_size < local_size else "STOR"
        sent = remote_size if command == "APPE" else 0

        def on_chunk(chunk: bytes) -> None:
            nonlocal sent
            sent += len(chunk)
            if progress_cb is not None:
                progress_cb(sent, local_size)

        with open(local_path, "rb") as handle:
            if command == "APPE":
                handle.seek(remote_size)
            self.ftp.storbinary(f"{command} {remote_path}", handle, callback=on_chunk)

    def remove(self, remote_path: str, recursive: bool = False) -> None:
        remote_path = _norm(remote_path)
        if self.is_dir(remote_path):
            if recursive:
                for entry in self.listdir_entries(remote_path):
                    self.remove(entry.path, recursive=True)
            self.ftp.rmd(remote_path)
            return
        self.ftp.delete(remote_path)

    def rename(self, remote_path: str, new_remote_path: str) -> None:
        self._ensure_parent_dirs(new_remote_path)
        self.ftp.rename(_norm(remote_path), _norm(new_remote_path))

    def mkdir(self, remote_dir: str) -> None:
        remote_dir = _norm(remote_dir)
        if remote_dir == "/":
            return
        self._ensure_parent_dirs(posixpath.join(remote_dir, "placeholder"))
        if not self.exists(remote_dir):
            self.ftp.mkd(remote_dir)

    def copy(self, src_remote_path: str, dst_remote_path: str, recursive: bool = False) -> None:
        src = _norm(src_remote_path)
        dst = _norm(dst_remote_path)
        if self.is_dir(src):
            if not recursive:
                raise IsADirectoryError(src)
            self.mkdir(dst)
            for entry in self.listdir_entries(src):
                self.copy(entry.path, posixpath.join(dst, entry.name), recursive=True)
            return
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
        try:
            self.download(src, tmp_path)
            self.upload(tmp_path, dst)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def move(self, src_remote_path: str, dst_remote_path: str) -> None:
        self.rename(src_remote_path, dst_remote_path)

    def exists(self, remote_path: str) -> bool:
        remote_path = _norm(remote_path)
        if remote_path == "/":
            return True
        if self.is_dir(remote_path):
            return True
        try:
            self.ftp.voidcmd("TYPE I")
            self.ftp.size(remote_path)
            return True
        except Exception:
            return False

    def is_dir(self, remote_path: str) -> bool:
        remote_path = _norm(remote_path)
        current = self.ftp.pwd()
        try:
            self.ftp.cwd(remote_path)
            return True
        except Exception:
            return False
        finally:
            try:
                self.ftp.cwd(current)
            except Exception:
                pass

    def _ensure_parent_dirs(self, remote_path: str) -> None:
        parent = posixpath.dirname(_norm(remote_path))
        if parent in {"", "/"}:
            return
        parts = [part for part in parent.split("/") if part]
        current = ""
        for part in parts:
            current = _norm(posixpath.join(current, part))
            if not self.exists(current):
                try:
                    self.ftp.mkd(current)
                except error_perm:
                    if not self.exists(current):
                        raise
