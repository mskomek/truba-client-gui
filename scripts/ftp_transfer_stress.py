"""Loopback FTP integration/stress harness for the GUI transfer controller.

The harness is intentionally standalone and disposable.  It starts pyftpdlib
on 127.0.0.1 with an ephemeral port, drives RemoteDirPanel's real upload and
recursive-download planning path, verifies every byte, and deletes all data on
exit.  Nothing in the application is reconfigured or persisted.
"""

from __future__ import annotations

import argparse
import ftplib
import hashlib
import json
import os
import posixpath
import shutil
import socket
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterator

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
from PySide6.QtWidgets import QApplication

from truba_gui.services.files_base import RemoteEntry
from truba_gui.ui.widgets import remote_dir_panel as remote_panel_module
from truba_gui.ui.widgets.remote_dir_panel import RemoteDirPanel


SMALL_SIZE = 10 * 1024
FULL_LARGE_SIZE = 1024**3


@dataclass
class PhaseResult:
    name: str
    elapsed_seconds: float
    bytes_transferred: int
    throughput_mib_s: float
    completed_rows: int
    error_rows: list[str]
    pending_rows: list[str]
    max_observed_concurrency: int


class ConcurrencyTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.maximum = 0

    @contextmanager
    def transfer(self) -> Iterator[None]:
        with self._lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)
        try:
            yield
        finally:
            with self._lock:
                self.active -= 1


class LoopbackFtpBackend:
    """Minimal server-backed backend; every operation uses a fresh connection."""

    supports_parallel_transfers = True

    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.tracker = ConcurrencyTracker()
        self.connection_count = 0
        self._connection_lock = threading.Lock()

    @contextmanager
    def _ftp(self) -> Iterator[ftplib.FTP]:
        ftp = ftplib.FTP()
        ftp.connect(self.host, self.port, timeout=30)
        ftp.login(self.username, self.password)
        with self._connection_lock:
            self.connection_count += 1
        try:
            yield ftp
        finally:
            try:
                ftp.quit()
            except Exception:
                ftp.close()

    @staticmethod
    def _path(path: str) -> str:
        normalized = posixpath.normpath("/" + str(path or "/").lstrip("/"))
        if not normalized.startswith("/"):
            raise ValueError(f"unsafe remote path: {path}")
        return normalized

    def exists(self, remote_path: str) -> bool:
        path = self._path(remote_path)
        with self._ftp() as ftp:
            try:
                ftp.voidcmd(f"MLST {path}")
                return True
            except ftplib.error_perm:
                return False

    def is_dir(self, remote_path: str) -> bool:
        path = self._path(remote_path)
        with self._ftp() as ftp:
            try:
                ftp.cwd(path)
                return True
            except ftplib.error_perm:
                return False

    def mkdir(self, remote_dir: str) -> None:
        path = self._path(remote_dir)
        with self._ftp() as ftp:
            try:
                ftp.mkd(path)
            except ftplib.error_perm as exc:
                if not str(exc).startswith("550 File exists"):
                    raise

    def listdir(self, remote_dir: str) -> list[str]:
        return [entry.name for entry in self.listdir_entries(remote_dir)]

    def listdir_entries(self, remote_dir: str) -> list[RemoteEntry]:
        base = self._path(remote_dir)
        entries: list[RemoteEntry] = []
        with self._ftp() as ftp:
            for name, facts in ftp.mlsd(base):
                if name in {".", ".."}:
                    continue
                is_dir = facts.get("type") == "dir"
                entries.append(
                    RemoteEntry(
                        name=name,
                        path=posixpath.join(base.rstrip("/"), name) or "/",
                        is_dir=is_dir,
                        size=int(facts.get("size", "0")) if not is_dir else 0,
                    )
                )
        return entries

    def upload(self, local_path: str, remote_path: str, progress_cb=None) -> None:
        total = os.path.getsize(local_path)
        done = 0
        with self.tracker.transfer(), self._ftp() as ftp, open(local_path, "rb") as source:
            def on_block(block: bytes) -> None:
                nonlocal done
                done += len(block)
                if progress_cb is not None:
                    progress_cb(done, total)

            ftp.storbinary(f"STOR {self._path(remote_path)}", source, blocksize=1024 * 1024, callback=on_block)

    def download(self, remote_path: str, local_path: str, progress_cb=None) -> None:
        destination = Path(local_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.tracker.transfer(), self._ftp() as ftp:
            ftp.voidcmd("TYPE I")
            total = int(ftp.size(self._path(remote_path)) or 0)
            done = 0
            with destination.open("wb") as target:
                def on_block(block: bytes) -> None:
                    nonlocal done
                    target.write(block)
                    done += len(block)
                    if progress_cb is not None:
                        progress_cb(done, total)

                ftp.retrbinary(f"RETR {self._path(remote_path)}", on_block, blocksize=1024 * 1024)


@contextmanager
def ftp_server(root: Path, username: str, password: str) -> Iterator[tuple[str, int]]:
    authorizer = DummyAuthorizer()
    authorizer.add_user(username, password, str(root), perm="elradfmwMT")

    class HarnessHandler(FTPHandler):
        pass

    HarnessHandler.authorizer = authorizer
    HarnessHandler.banner = "TrubaGUI loopback stress harness"
    server = FTPServer(("127.0.0.1", 0), HarnessHandler)
    host, port = server.socket.getsockname()[:2]
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"timeout": 0.1, "blocking": True, "handle_exit": False},
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.25):
                break
        except OSError:
            time.sleep(0.05)
    else:
        server.close_all()
        raise TimeoutError("loopback FTP server did not become ready")
    try:
        yield str(host), int(port)
    finally:
        server.close_all()
        thread.join(timeout=5)


def _write_sparse(path: Path, size: int, seed: bytes) -> None:
    with path.open("wb") as stream:
        stream.write(seed)
        stream.seek(size - len(seed))
        stream.write(seed[::-1])


def build_dataset(root: Path, *, large_size: int) -> dict[str, int]:
    sizes: dict[str, int] = {}
    large_locations = {(2, 3), (8, 4)}
    for folder_index in range(10):
        folder = root / f"folder_{folder_index:02d}"
        folder.mkdir(parents=True)
        for file_index in range(5):
            relative = f"folder_{folder_index:02d}/file_{file_index:02d}.bin"
            path = root / relative
            seed = f"TrubaGUI:{relative}:".encode("ascii")
            if (folder_index, file_index) in large_locations:
                _write_sparse(path, large_size, seed)
            else:
                repeated = (seed * ((SMALL_SIZE // len(seed)) + 1))[:SMALL_SIZE]
                path.write_bytes(repeated)
            sizes[relative] = path.stat().st_size
    return sizes


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def manifest(root: Path) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        result[relative] = {"size": path.stat().st_size, "sha256": sha256_file(path)}
    return result


def wait_for_phase(
    app: QApplication,
    panel: RemoteDirPanel,
    *,
    phase: str,
    expected_bytes: int,
    tracker: ConcurrencyTracker,
    timeout_seconds: int,
) -> PhaseResult:
    deadline = time.monotonic() + timeout_seconds
    started = time.monotonic()
    controllers = list(panel._transfer_dialogs)
    while not controllers and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
        controllers = list(panel._transfer_dialogs)
    if not controllers:
        raise TimeoutError(
            f"{phase}: transfer controller was not created before timeout"
        )
    controller = controllers[-1]
    while controller._running and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    if controller._running:
        for active in list(panel._transfer_dialogs):
            active.cancel_all()
        cancel_deadline = time.monotonic() + 15
        while controller._running and time.monotonic() < cancel_deadline:
            app.processEvents()
            time.sleep(0.01)
        raise TimeoutError(f"{phase}: timed out after {timeout_seconds}s; cancellation requested")
    app.processEvents()
    elapsed = time.monotonic() - started
    errors = [f"{item.label()}: {error}" for item, error in controller._errors]
    pending = [item.label() for item in controller._pending]
    completed_count = len(controller._completed)
    if controller in panel._transfer_dialogs:
        controller.reject()
        app.processEvents()
    return PhaseResult(
        name=phase,
        elapsed_seconds=elapsed,
        bytes_transferred=expected_bytes,
        throughput_mib_s=(expected_bytes / (1024**2)) / elapsed if elapsed else 0.0,
        completed_rows=completed_count,
        error_rows=errors,
        pending_rows=pending,
        max_observed_concurrency=tracker.maximum,
    )


def cancel_and_drain(app: QApplication, panel: RemoteDirPanel, timeout_seconds: int = 30) -> None:
    """Stop controller workers before the FTP server and temp root disappear."""
    controllers = list(panel._transfer_dialogs)
    for controller in controllers:
        controller.cancel_all()
    deadline = time.monotonic() + timeout_seconds
    while any(controller._running for controller in controllers) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    still_running = [controller for controller in controllers if controller._running]
    for controller in controllers:
        if controller in panel._transfer_dialogs:
            controller.reject()
    app.processEvents()
    panel.shutdown()
    panel.deleteLater()
    app.processEvents()
    if still_running:
        raise TimeoutError(
            f"{len(still_running)} transfer controller(s) did not stop during cleanup"
        )


def remove_temp_root(temp_root: Path) -> None:
    """Remove this run's known temp root, retrying transient Windows handles."""
    last_error: OSError | None = None
    for _attempt in range(20):
        try:
            shutil.rmtree(temp_root)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"temporary cleanup failed for {temp_root}: {last_error}")


def run(mode: str, parallel: int, timeout_seconds: int) -> dict[str, object]:
    large_size = 4 * 1024 * 1024 if mode == "smoke" else FULL_LARGE_SIZE
    username = "trubagui_stress"
    password = "ephemeral-only"
    app = QApplication.instance() or QApplication([])
    original_parallelism: Callable[[], int] = remote_panel_module.get_transfer_parallelism
    remote_panel_module.get_transfer_parallelism = lambda: parallel
    temp_root = Path(tempfile.mkdtemp(prefix="trubagui_ftp_stress_"))
    result: dict[str, object] | None = None
    try:
        source_parent = temp_root / "source"
        dataset_root = source_parent / "dataset"
        server_root = temp_root / "server"
        download_root = temp_root / "download"
        dataset_root.mkdir(parents=True)
        server_root.mkdir()
        download_root.mkdir()
        expected_sizes = build_dataset(dataset_root, large_size=large_size)
        expected_bytes = sum(expected_sizes.values())
        source_manifest = manifest(dataset_root)
        preflight_calls = 0

        with ftp_server(server_root, username, password) as (host, port):
            backend = LoopbackFtpBackend(host, port, username, password)
            panel = RemoteDirPanel("FTP stress")
            panel.set_session({"files": backend})
            panel.set_transfer_dialog_visible(False)

            try:

                def approve_preflight(*_args, **_kwargs) -> bool:
                    nonlocal preflight_calls
                    preflight_calls += 1
                    return True

                panel._confirm_transfer_plan = approve_preflight
                if not panel._apply_local_upload_incremental([str(dataset_root)], "/"):
                    raise RuntimeError("upload plan was rejected or empty")
                upload = wait_for_phase(
                    app,
                    panel,
                    phase="upload",
                    expected_bytes=expected_bytes,
                    tracker=backend.tracker,
                    timeout_seconds=timeout_seconds,
                )
                if upload.error_rows or upload.pending_rows:
                    raise RuntimeError(f"upload incomplete: errors={upload.error_rows}, pending={upload.pending_rows}")
                server_manifest = manifest(server_root / "dataset")
                if server_manifest != source_manifest:
                    raise AssertionError("server manifest differs from source after upload")

                backend.tracker.maximum = 0
                if not panel._apply_remote_download_incremental(
                    ["/dataset"],
                    str(download_root),
                ):
                    raise RuntimeError("download plan was rejected or empty")
                download = wait_for_phase(
                    app,
                    panel,
                    phase="download",
                    expected_bytes=expected_bytes,
                    tracker=backend.tracker,
                    timeout_seconds=timeout_seconds,
                )
                if download.error_rows or download.pending_rows:
                    raise RuntimeError(f"download incomplete: errors={download.error_rows}, pending={download.pending_rows}")
                downloaded_manifest = manifest(download_root / "dataset")
                if downloaded_manifest != source_manifest:
                    raise AssertionError("download manifest differs from source")
                folder_count = sum(1 for item in dataset_root.iterdir() if item.is_dir())
            finally:
                cancel_and_drain(app, panel)

        result = {
            "status": "PASS",
            "mode": mode,
            "configured_parallelism": parallel,
            "effective_parallelism": parallel,
            "folders": folder_count,
            "files": len(source_manifest),
            "small_files": sum(1 for value in expected_sizes.values() if value == SMALL_SIZE),
            "large_files": sum(1 for value in expected_sizes.values() if value == large_size),
            "large_file_size": large_size,
            "dataset_bytes": expected_bytes,
            "all_sha256_verified": True,
            "preflight_auto_approvals": preflight_calls,
            "ftp_connections_opened": backend.connection_count,
            "upload": asdict(upload),
            "download": asdict(download),
        }
    finally:
        remote_panel_module.get_transfer_parallelism = original_parallelism
        remove_temp_root(temp_root)
    if result is None:
        raise RuntimeError("stress run completed without a result")
    result["temporary_cleanup_confirmed"] = not temp_root.exists()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a disposable localhost FTP upload/download integration test "
            "through TrubaGUI's real RemoteDirPanel/TransferDialog controller."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("smoke", "full"),
        default="smoke",
        help="smoke uses two 4 MiB files; full uses two sparse 1 GiB source files",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=4,
        help="configured controller concurrency (4-10; default: 4)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1200,
        help="maximum seconds allowed for each upload/download phase (default: 1200)",
    )
    args = parser.parse_args()
    if not 4 <= args.parallel <= 10:
        parser.error("--parallel must be between 4 and 10")
    try:
        result = run(args.mode, args.parallel, args.timeout)
    except Exception as exc:
        result = {"status": "FAIL", "mode": args.mode, "error": repr(exc)}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
