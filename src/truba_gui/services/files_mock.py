from __future__ import annotations

import os
import posixpath
import stat
import time
from pathlib import Path
from typing import Dict, List, Tuple
from .files_base import FilesBackend, RemoteEntry


def _norm(path: str) -> str:
    value = (path or "/").replace("\\", "/").strip() or "/"
    if not value.startswith("/"):
        value = "/" + value
    value = posixpath.normpath(value)
    return "/" if value == "." else value


class MockFilesBackend(FilesBackend):
    supports_parallel_transfers = True

    def __init__(self):
        now = int(time.time())
        self._files: Dict[str, bytes] = {
            "/arf/scratch/user/example.txt": b"Mock file content\nline2\n",
            "/arf/scratch/user/job.slurm": b"#!/bin/bash\n#SBATCH --output=static_output.txt\n#SBATCH --error=static_error.txt\n",
            "/arf/scratch/user/static_output.txt": b"stdout: hello\n",
            "/arf/scratch/user/static_error.txt": b"stderr: none\n",
            "/arf/scratch/user/project/input.dat": b"1 2 3\n",
            "/arf/scratch/user/project/nested/result.bin": b"\x00\x01\x02mock-binary",
            "/arf/home/user/readme.md": b"# Mock Home\n",
        }
        self._dirs = {
            "/",
            "/arf",
            "/arf/scratch",
            "/arf/scratch/user",
            "/arf/scratch/user/project",
            "/arf/scratch/user/project/nested",
            "/arf/home",
            "/arf/home/user",
        }
        self._mt: Dict[str, int] = {k: now for k in [*self._dirs, *self._files]}
        self._mode: Dict[str, int] = {
            **{k: stat.S_IFDIR | 0o755 for k in self._dirs},
            **{k: stat.S_IFREG | 0o644 for k in self._files},
        }

    def _touch(self, path: str) -> None:
        self._mt[_norm(path)] = int(time.time())

    def _ensure_parent_dirs(self, path: str) -> None:
        cur = posixpath.dirname(_norm(path))
        pending = []
        while cur and cur not in self._dirs:
            pending.append(cur)
            cur = posixpath.dirname(cur)
        for item in reversed(pending):
            self._dirs.add(item)
            self._touch(item)

    def _children(self, remote_dir: str) -> List[str]:
        base = _norm(remote_dir).rstrip("/")
        prefix = "/" if base == "" else base + "/"
        names = set()
        for path in [*self._dirs, *self._files]:
            if path == base or not path.startswith(prefix):
                continue
            rest = path[len(prefix):]
            if rest:
                names.add(rest.split("/", 1)[0])
        return sorted(names)

    def listdir(self, remote_dir: str) -> List[str]:
        remote_dir = _norm(remote_dir)
        if remote_dir not in self._dirs:
            raise FileNotFoundError(remote_dir)
        return self._children(remote_dir)

    def listdir_entries(self, remote_dir: str) -> List[RemoteEntry]:
        remote_dir = _norm(remote_dir)
        if remote_dir not in self._dirs:
            raise FileNotFoundError(remote_dir)
        entries = []
        for name in self.listdir(remote_dir):
            full = _norm(posixpath.join(remote_dir, name))
            is_dir = full in self._dirs
            mode = self._mode.get(full, (stat.S_IFDIR if is_dir else stat.S_IFREG) | (0o755 if is_dir else 0o644))
            size = 0 if is_dir else len(self._files.get(full, b""))
            entries.append(RemoteEntry(name=name, path=full, is_dir=is_dir, size=size, mtime=self._mt.get(full, 0), mode=mode))
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def read_text(self, remote_path: str) -> str:
        remote_path = _norm(remote_path)
        if remote_path not in self._files:
            raise FileNotFoundError(remote_path)
        return self._files[remote_path].decode("utf-8", errors="replace")

    def write_text(self, remote_path: str, text: str) -> None:
        remote_path = _norm(remote_path)
        self._ensure_parent_dirs(remote_path)
        self._files[remote_path] = text.encode("utf-8")
        self._mode[remote_path] = stat.S_IFREG | 0o644
        self._touch(remote_path)

    def stat(self, remote_path: str) -> Tuple[int,int]:
        remote_path = _norm(remote_path)
        if remote_path in self._dirs:
            return (0, self._mt.get(remote_path, 0))
        if remote_path not in self._files:
            raise FileNotFoundError(remote_path)
        return (len(self._files[remote_path]), self._mt.get(remote_path, 0))

    def download(self, remote_path: str, local_path: str, progress_cb=None) -> None:
        remote_path = _norm(remote_path)
        if remote_path not in self._files:
            raise FileNotFoundError(remote_path)
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        data = self._files[remote_path]
        Path(local_path).write_bytes(data)
        if progress_cb is not None:
            progress_cb(len(data), len(data))

    def upload(self, local_path: str, remote_path: str) -> None:
        remote_path = _norm(remote_path)
        self._ensure_parent_dirs(remote_path)
        self._files[remote_path] = Path(local_path).read_bytes()
        self._mode[remote_path] = stat.S_IFREG | 0o644
        self._touch(remote_path)

    def exists(self, remote_path: str) -> bool:
        remote_path = _norm(remote_path)
        return remote_path in self._files or remote_path in self._dirs

    def is_dir(self, remote_path: str) -> bool:
        return _norm(remote_path) in self._dirs

    def mkdir(self, remote_dir: str) -> None:
        remote_dir = _norm(remote_dir)
        self._ensure_parent_dirs(remote_dir)
        self._dirs.add(remote_dir)
        self._mode[remote_dir] = stat.S_IFDIR | 0o755
        self._touch(remote_dir)

    def remove(self, remote_path: str, recursive: bool = False) -> None:
        remote_path = _norm(remote_path)
        if remote_path in self._files:
            del self._files[remote_path]
            self._mt.pop(remote_path, None)
            self._mode.pop(remote_path, None)
            return
        if remote_path not in self._dirs:
            raise FileNotFoundError(remote_path)
        children = [
            path for path in [*self._dirs, *self._files]
            if path != remote_path and path.startswith(remote_path.rstrip("/") + "/")
        ]
        if children and not recursive:
            raise IsADirectoryError(remote_path)
        for path in children:
            self._files.pop(path, None)
            self._dirs.discard(path)
            self._mt.pop(path, None)
            self._mode.pop(path, None)
        if remote_path != "/":
            self._dirs.discard(remote_path)
            self._mt.pop(remote_path, None)
            self._mode.pop(remote_path, None)

    def rename(self, remote_path: str, new_remote_path: str) -> None:
        self.move(remote_path, new_remote_path)

    def copy(self, src_remote_path: str, dst_remote_path: str, recursive: bool = False) -> None:
        src = _norm(src_remote_path)
        dst = _norm(dst_remote_path)
        if src in self._files:
            self._ensure_parent_dirs(dst)
            self._files[dst] = bytes(self._files[src])
            self._mode[dst] = stat.S_IFREG | stat.S_IMODE(self._mode.get(src, stat.S_IFREG | 0o644))
            self._touch(dst)
            return
        if src not in self._dirs:
            raise FileNotFoundError(src)
        children = [
            path for path in [*self._dirs, *self._files]
            if path != src and path.startswith(src.rstrip("/") + "/")
        ]
        if children and not recursive:
            raise IsADirectoryError(src)
        self.mkdir(dst)
        for path in sorted(children):
            target = dst + path[len(src):]
            if path in self._dirs:
                self.mkdir(target)
            else:
                self._ensure_parent_dirs(target)
                self._files[target] = bytes(self._files[path])
                self._mode[target] = stat.S_IFREG | stat.S_IMODE(self._mode.get(path, stat.S_IFREG | 0o644))
                self._touch(target)

    def move(self, src_remote_path: str, dst_remote_path: str) -> None:
        src = _norm(src_remote_path)
        dst = _norm(dst_remote_path)
        if src not in self._files and src not in self._dirs:
            raise FileNotFoundError(src)
        self.copy(src, dst, recursive=True)
        self.remove(src, recursive=True)

    def chmod(self, remote_path: str, mode: int) -> None:
        remote_path = _norm(remote_path)
        if remote_path not in self._files and remote_path not in self._dirs:
            raise FileNotFoundError(remote_path)
        file_type = stat.S_IFDIR if remote_path in self._dirs else stat.S_IFREG
        self._mode[remote_path] = file_type | stat.S_IMODE(mode)
        self._touch(remote_path)
