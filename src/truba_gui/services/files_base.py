from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class RemoteEntry:
    name: str
    path: str
    is_dir: bool
    size: int = 0
    mtime: int = 0  # unix epoch seconds
    mode: int = 0

class FilesBackend(ABC):
    @abstractmethod
    def listdir(self, remote_dir: str) -> List[str]:
        """Backward-compatible: return names."""
        raise NotImplementedError

    @abstractmethod
    def listdir_entries(self, remote_dir: str) -> List[RemoteEntry]:
        """Preferred: return rich entries."""
        raise NotImplementedError

    @abstractmethod
    def read_text(self, remote_path: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def write_text(self, remote_path: str, text: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def stat(self, remote_path: str) -> Tuple[int, int]:
        """Return (size, mtime)."""
        raise NotImplementedError

    @abstractmethod
    def download(self, remote_path: str, local_path: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def upload(self, local_path: str, remote_path: str) -> None:
        raise NotImplementedError

    # --- Optional file operations (used by RemoteDirPanel context menu) ---
    # Backends that don't support these can rely on the default NotImplementedError.
    def remove(self, remote_path: str, recursive: bool = False) -> None:
        raise NotImplementedError

    def rename(self, remote_path: str, new_remote_path: str) -> None:
        raise NotImplementedError

    def mkdir(self, remote_dir: str) -> None:
        raise NotImplementedError

    def copy(self, src_remote_path: str, dst_remote_path: str, recursive: bool = False) -> None:
        raise NotImplementedError

    def move(self, src_remote_path: str, dst_remote_path: str) -> None:
        raise NotImplementedError
