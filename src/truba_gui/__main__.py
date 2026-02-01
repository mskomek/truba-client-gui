"""Entry point.

Not: IDE'lerde bazen modül yerine dosya olarak çalıştırılır (script path).
Bu durumda relative import (from .app ...) "parent package" olmadığı için patlar.

Bu dosya hem `python -m truba_gui` hem de doğrudan çalıştırma için güvenli olacak
şekilde yazılmıştır.
"""

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    # script olarak çalıştırıldı -> src/ dizinini sys.path'e ekle
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from truba_gui.app import main
else:
    from .app import main

if __name__ == "__main__":
    raise SystemExit(main())
