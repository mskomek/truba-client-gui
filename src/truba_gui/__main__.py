"""Entry point.

Not: IDE'lerde bazen modül yerine dosya olarak çalıştırılır (script path).
Bu durumda relative import (from .app ...) "parent package" olmadığı için patlar.

Bu dosya hem `python -m truba_gui` hem de doğrudan çalıştırma için güvenli olacak
şekilde yazılmıştır.
"""

import importlib.util
import os
import sys
from pathlib import Path


def _load_source_performance_probe():
    """Load the optional source-only profiler without packaging it."""
    if os.environ.get("TRUBA_GUI_PERF_DEBUG") != "1":
        return None
    if bool(getattr(sys, "frozen", False)):
        return None

    probe_path = Path(__file__).resolve().parents[2] / "devtools" / "performance_probe.py"
    if not probe_path.is_file():
        return None

    try:
        spec = importlib.util.spec_from_file_location("_truba_gui_perf_probe", probe_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module.start(Path(__file__).resolve().parents[2])
        return module
    except Exception as exc:
        print(f"[perf-debug] profiler could not start: {exc}", file=sys.stderr)
        return None


_PERFORMANCE_PROBE = _load_source_performance_probe()

if __package__ is None or __package__ == "":
    # script olarak çalıştırıldı -> src/ dizinini sys.path'e ekle
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from truba_gui.app import main
else:
    from .app import main

if _PERFORMANCE_PROBE is not None:
    _PERFORMANCE_PROBE.mark("application_imports_complete")

if __name__ == "__main__":
    raise SystemExit(main())
