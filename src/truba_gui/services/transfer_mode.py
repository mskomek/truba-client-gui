from __future__ import annotations

import os
import inspect
import tempfile
from pathlib import Path


AUTO = "auto"
BINARY = "binary"
ASCII = "ascii"
TRANSFER_MODES = (AUTO, BINARY, ASCII)

TEXT_EXTENSIONS = {
    ".bash",
    ".cfg",
    ".conf",
    ".csv",
    ".dat",
    ".ini",
    ".json",
    ".log",
    ".md",
    ".out",
    ".py",
    ".sbatch",
    ".sh",
    ".slurm",
    ".text",
    ".toml",
    ".tsv",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


def normalize_transfer_mode(value: str, default: str = AUTO) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in TRANSFER_MODES else default


def looks_binary(data: bytes) -> bool:
    if b"\x00" in data:
        return True
    if not data:
        return False
    try:
        data[:8192].decode("utf-8")
    except UnicodeDecodeError:
        return True
    sample = data[:8192]
    suspicious = sum(
        1 for byte in sample if byte < 9 or (13 < byte < 32)
    )
    return suspicious / len(sample) > 0.10


def is_known_text_path(path: str) -> bool:
    name = Path(path).name
    if not Path(name).suffix:
        return False
    return any(name.casefold().endswith(ext) for ext in TEXT_EXTENSIONS)


def resolve_transfer_mode(path: str, requested: str, sample: bytes | None = None) -> str:
    requested = normalize_transfer_mode(requested)
    if requested == BINARY:
        return BINARY
    if sample is not None and looks_binary(sample):
        if requested == ASCII:
            raise ValueError("ASCII transfer rejected because binary content was detected.")
        return BINARY
    if requested == ASCII:
        return ASCII
    return ASCII if is_known_text_path(path) else BINARY


def _ascii_bytes_for_remote(data: bytes) -> bytes:
    text = data.decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _ascii_bytes_for_local(data: bytes) -> bytes:
    text = data.decode("utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.replace("\n", os.linesep).encode("utf-8")


def _upload_file(files, local_path: str, remote_path: str, progress_cb=None) -> None:
    try:
        signature = inspect.signature(files.upload)
        if "progress_cb" in signature.parameters:
            files.upload(local_path, remote_path, progress_cb=progress_cb)
            return
    except (TypeError, ValueError):
        pass
    files.upload(local_path, remote_path)


def upload_with_mode(
    files,
    local_path: str,
    remote_path: str,
    requested: str,
    progress_cb=None,
) -> str:
    with open(local_path, "rb") as source:
        sample = source.read(8192)
    effective = resolve_transfer_mode(local_path, requested, sample)
    if effective == BINARY:
        _upload_file(files, local_path, remote_path, progress_cb=progress_cb)
        return effective
    # ASCII conversion intentionally materializes the source so its line endings
    # can be normalized before the backend upload. Binary transfers stream the
    # original path and never load the full file merely for classification.
    data = Path(local_path).read_bytes()
    converted = _ascii_bytes_for_remote(data)
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False) as temp:
            temp.write(converted)
            temp_path = temp.name
        _upload_file(files, temp_path, remote_path, progress_cb=progress_cb)
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
    return effective


def _download_file(files, remote_path: str, local_path: str, progress_cb=None) -> None:
    try:
        signature = inspect.signature(files.download)
        if "progress_cb" in signature.parameters:
            files.download(remote_path, local_path, progress_cb=progress_cb)
            return
    except (TypeError, ValueError):
        pass
    files.download(remote_path, local_path)


def download_with_mode(
    files,
    remote_path: str,
    local_path: str,
    requested: str,
    progress_cb=None,
) -> str:
    destination = Path(local_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _download_file(files, remote_path, str(destination), progress_cb=progress_cb)
    try:
        sample = destination.read_bytes()[:8192]
    except OSError:
        sample = b""
    return resolve_transfer_mode(remote_path, requested, sample)
