"""Передача файлов между панелями."""

import os
import shutil
import tempfile

from PyQt6.QtWidgets import QMessageBox


def transfer_file(src_panel, dst_panel, entry):
    if not src_panel.provider or not dst_panel.provider:
        return False

    dst_dir = getattr(dst_panel.provider, "cwd", None)
    if dst_dir is None:
        return False
    dst_path = dst_dir.rstrip("/") + "/" + entry.name

    tmpdir = tempfile.mkdtemp(prefix="freemius_xfer_")
    local_tmp = os.path.join(tmpdir, entry.name)
    try:
        src = src_panel.provider
        if src.kind == "local":
            shutil.copy2(entry.path, local_tmp)
        else:
            src.get_file(entry.path, local_tmp)

        dst = dst_panel.provider
        if dst.kind == "local":
            shutil.copy2(local_tmp, dst_path)
        else:
            dst.put_file(local_tmp, dst_path)
    except Exception as e:
        QMessageBox.critical(src_panel, "Ошибка передачи", str(e))
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return True
