from __future__ import annotations

from typing import Optional

from truba_gui.core.debug_support import log_exception_with_id, new_error_id
from truba_gui.core.i18n import t


def show_exception(
    parent,
    *,
    title: Optional[str] = None,
    user_message: Optional[str] = None,
    exc: Optional[BaseException] = None,
    area: str = "GEN",
) -> None:
    try:
        from PySide6.QtWidgets import QMessageBox
    except Exception:
        return

    if exc is not None:
        err_id = log_exception_with_id(area, exc)
    else:
        err_id = new_error_id(area)

    ttl = title or t("common.error")
    label = t("common.error_code")
    msg = (user_message or t("common.error")) + f"\n\n{label}: {err_id}"
    QMessageBox.critical(parent, ttl, msg)
