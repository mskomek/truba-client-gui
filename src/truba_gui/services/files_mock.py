from __future__ import annotations

import os
import time
from typing import Dict, List, Tuple
from .files_base import FilesBackend, RemoteEntry

class MockFilesBackend(FilesBackend):
    def __init__(self):
        # in-memory fs: path -> text
        self._files: Dict[str, str] = {
            "/arf/scratch/user/example.txt": "Mock file content\nline2\n",
            "/arf/scratch/user/job.slurm": "#!/bin/bash\n#SBATCH --output=static_output.txt\n#SBATCH --error=static_error.txt\n",
            "/arf/scratch/user/static_output.txt": "stdout: hello\n",
            "/arf/scratch/user/static_error.txt": "stderr: none\n",
        }
        self._mt: Dict[str, int] = {k:int(time.time()) for k in self._files}

    def listdir(self, remote_dir: str) -> List[str]:
        remote_dir = remote_dir.rstrip("/")
        names=set()
        for p in self._files:
            if p.startswith(remote_dir + "/"):
                rest=p[len(remote_dir)+1:]
                names.add(rest.split("/")[0])
        return sorted(names)

    def listdir_entries(self, remote_dir: str) -> List[RemoteEntry]:
        remote_dir = remote_dir.rstrip("/")
        entries=[]
        for name in self.listdir(remote_dir):
            full=f"{remote_dir}/{name}"
            is_dir = any(k.startswith(full + "/") for k in self._files)
            size=len(self._files.get(full,"").encode("utf-8")) if not is_dir else 0
            entries.append(RemoteEntry(name=name, path=full, is_dir=is_dir, size=size, mtime=self._mt.get(full,0), mode=0))
        entries.sort(key=lambda e:(not e.is_dir, e.name.lower()))
        return entries

    def read_text(self, remote_path: str) -> str:
        if remote_path not in self._files:
            raise FileNotFoundError(remote_path)
        return self._files[remote_path]

    def write_text(self, remote_path: str, text: str) -> None:
        self._files[remote_path]=text
        self._mt[remote_path]=int(time.time())

    def stat(self, remote_path: str) -> Tuple[int,int]:
        txt=self._files.get(remote_path, "")
        return (len(txt.encode("utf-8")), self._mt.get(remote_path,0))

    def download(self, remote_path: str, local_path: str) -> None:
        txt=self.read_text(remote_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(txt)

    def upload(self, local_path: str, remote_path: str) -> None:
        with open(local_path, "r", encoding="utf-8", errors="replace") as f:
            txt=f.read()
        self.write_text(remote_path, txt)
