import os
import json
import subprocess
import threading
import time

from ppr_color_service import ColorBatchResult

DISK_CACHE_FILE = "Кэш_цветов_графиков.json"

_file_color_cache = {}
CACHE_VERSION = "v6-display-format-required"
_disk_cache = None
_disk_cache_lock = threading.Lock()
_disk_cache_dirty = False


def _com_use_display_format(fpath):
    # ППР могут быть закрашены условным форматированием. Interior не отражает
    # такой цвет, поэтому производственный контур всегда читает DisplayFormat.
    return True


def _load_disk_cache():
    global _disk_cache
    if _disk_cache is not None:
        return _disk_cache
    try:
        from data_manager import db_load_excel_colors, db_prune_excel_colors
        db_prune_excel_colors(active_version=CACHE_VERSION, max_entries=64)
        _disk_cache = db_load_excel_colors()
    except Exception:
        _disk_cache = {}
    return _disk_cache


def _save_disk_cache():
    global _disk_cache_dirty
    disk = _load_disk_cache()
    try:
        from data_manager import db_save_excel_color
        for k, v in disk.items():
            db_save_excel_color(k, v)
        _disk_cache_dirty = False
    except Exception:
        pass


def _mark_disk_cache_dirty():
    global _disk_cache_dirty
    _disk_cache_dirty = True


def flush_disk_cache_if_dirty():
    if _disk_cache_dirty:
        with _disk_cache_lock:
            _save_disk_cache()


def _cache_key(fpath):
    abspath = os.path.abspath(fpath)
    try:
        stat = os.stat(abspath)
        mtime_ns = stat.st_mtime_ns
        size = stat.st_size
    except OSError:
        mtime_ns = 0
        size = 0
    return abspath, mtime_ns, size, CACHE_VERSION


def _disk_key(fpath):
    abspath, mtime_ns, size, version = _cache_key(fpath)
    return f"{abspath}|{mtime_ns}|{size}|{version}"


def _empty_cache_entry():
    return {"checked": set(), "colored": set()}


def _normalize_cache_entry(value):
    if not isinstance(value, dict):
        return _empty_cache_entry()
    return {
        "checked": set(value.get("checked", set())),
        "colored": set(value.get("colored", set())),
    }


class ColorCheckError(RuntimeError):
    """Excel did not reliably determine the color of every requested cell."""


def _validate_worker_payload(payload, requested, basename):
    try:
        batch = ColorBatchResult.from_payload(payload)
    except (TypeError, ValueError) as exc:
        raise ColorCheckError(
            f"Устаревший формат ответа проверки цветов для {basename}"
        ) from exc

    checked = batch.checked
    colored = batch.colored
    unexpected = colored - checked
    unknown = batch.unknown | (requested - checked)
    if not batch.ok or unknown or unexpected:
        details = batch.errors[:3]
        if unknown:
            details.append(f"не проверено ячеек: {len(unknown)}")
        if unexpected:
            details.append(f"некорректных координат: {len(unexpected)}")
        raise ColorCheckError(
            f"Неполная проверка цветов для {basename}: " + "; ".join(details)
        )
    return checked, colored


_excel_lock = threading.RLock()


def _com_init():
    try:
        import pythoncom
        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
        return True
    except Exception:
        try:
            import pythoncom
            pythoncom.CoInitialize()
            return True
        except Exception:
            return False


def _com_uninit():
    try:
        import gc
        gc.collect()
        import pythoncom
        try:
            # pythoncom.CoUninitialize()
            pass
        except OSError:
            pass
        except Exception:
            pass
    except Exception:
        pass


def _kill_excel_processes():
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            ["taskkill", "/F", "/IM", "EXCEL.EXE"],
            capture_output=True,
            timeout=12,
            creationflags=flags,
        )
    except Exception:
        pass


def _safe_excel_quit(excel):
    if excel is None:
        return
    with _excel_lock:
        try:
            excel.DisplayAlerts = False
        except Exception:
            pass
        try:
            count = int(excel.Workbooks.Count)
            for i in range(count, 0, -1):
                try:
                    excel.Workbooks(i).Close(SaveChanges=False)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            excel.Quit()
        except Exception:
            pass
    time.sleep(0.6)


def release_excel_com(force_kill=False, wait_s=0.8):
    """
    Освободить Excel. force_kill — завершить EXCEL.EXE (безопасно из воркера).
    """
    if force_kill:
        _kill_excel_processes()
    if wait_s > 0:
        time.sleep(wait_s)


class ExcelColorSession:
    """Обертка для вызова внешнего процесса COM (excel_worker.py)."""

    def __init__(self, force_refresh=False):
        self._failures = []
        self._aborted = False
        self._process = None
        self._force_refresh = bool(force_refresh)

    @property
    def failures(self):
        return list(self._failures)

    def __enter__(self):
        self._aborted = False
        return self

    def abort(self):
        self._aborted = True
        if self._process:
            try:
                self._process.kill()
            except Exception:
                pass
        _kill_excel_processes()

    def __exit__(self, exc_type, exc, tb):
        flush_disk_cache_if_dirty()
        return False

    def _run_excel_worker(self, fpath, cells_list, cancel_check=None, progress_cb=None):
        cells_list = list(cells_list)
        if not cells_list:
            return set(), set()

        if self._aborted or (cancel_check and cancel_check()):
            raise ColorCheckError("Проверка цветов Excel отменена")

        import tempfile
        import sys

        abs_path = os.path.abspath(fpath)
        use_display = _com_use_display_format(abs_path)
        basename = os.path.basename(abs_path)

        if progress_cb:
            progress_cb(0, 0, f"Открываю {basename} в Excel (внешний процесс)…")

        worker_script = os.path.join(os.path.dirname(__file__), "excel_worker.py")
        data = {
            "use_display": use_display,
            "cells": [(str(s), int(r), int(c)) for s, r, c in cells_list],
        }

        fd, tmp_file = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)

            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE

            from ssz_config import CONFIG

            exe_lower = sys.executable.lower()
            if exe_lower.endswith("python.exe") or exe_lower.endswith("pythonw.exe"):
                cmd = [sys.executable, worker_script, abs_path, tmp_file]
            else:
                cmd = [sys.executable, "--excel-worker", worker_script, abs_path, tmp_file]

            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                startupinfo=si,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            stdout, stderr = self._process.communicate(
                timeout=float(CONFIG.get("com_file_timeout_s", 90.0))
            )
            returncode = self._process.returncode
            self._process = None

            if returncode != 0:
                raise ColorCheckError(
                    f"Процесс проверки цветов завершился с кодом {returncode}: "
                    f"{stderr.strip() or basename}"
                )
            try:
                payload = json.loads(stdout.strip())
            except Exception as exc:
                raise ColorCheckError(
                    f"Некорректный ответ проверки цветов для {basename}"
                ) from exc

            requested = set(cells_list)
            return _validate_worker_payload(payload, requested, basename)
        except subprocess.TimeoutExpired as exc:
            if self._process:
                self._process.kill()
                self._process = None
            _kill_excel_processes()
            raise ColorCheckError(f"Таймаут процесса COM: {basename}") from exc
        finally:
            try:
                os.remove(tmp_file)
            except Exception:
                pass

    def check_cells(self, fpath, cells_list, cancel_check=None, progress_cb=None):
        requested = {
            (str(s), int(r), int(c)) for s, r, c in cells_list
        }
        if not requested:
            return set()

        key = _cache_key(fpath)
        if key in _file_color_cache:
            entry = _normalize_cache_entry(_file_color_cache[key])
        else:
            disk = _load_disk_cache()
            dk = _disk_key(fpath)
            entry = _normalize_cache_entry(disk.get(dk))
            _file_color_cache[key] = entry

        if self._force_refresh:
            entry["checked"].difference_update(requested)
            entry["colored"].difference_update(requested)

        missing = requested - entry["checked"]
        if not missing:
            return requested & entry["colored"]

        try:
            checked, colored = self._run_excel_worker(
                fpath, missing, cancel_check, progress_cb
            )
        except ColorCheckError as exc:
            self._failures.append(str(exc))
            raise

        entry["checked"].update(checked)
        entry["colored"].update(colored)
        _file_color_cache[key] = entry
        disk = _load_disk_cache()
        dk = _disk_key(fpath)
        with _disk_cache_lock:
            disk[dk] = entry
            _mark_disk_cache_dirty()
        return requested & entry["colored"]


def is_plan_cell_colored_com(cache, sheet_name, row, col):
    if not cache:
        return False
    row = int(row)
    col = int(col)
    for name in (sheet_name, str(sheet_name).strip()):
        if (name, row, col) in cache:
            return True
    return False


def get_xls_color_cache(fpath):
    """Обратная совместимость: полный кэш файла (устарело, используйте ExcelColorSession)."""
    key = _cache_key(fpath)
    if key in _file_color_cache:
        return _normalize_cache_entry(_file_color_cache[key])["colored"]
    session = ExcelColorSession()
    with session:
        cells = []
        try:
            import xlrd
            wb = xlrd.open_workbook(fpath, formatting_info=True)
            for si in range(wb.nsheets):
                ws = wb.sheet_by_index(si)
                name = ws.name
                for row in range(DATA_ROW_START, min(DATA_ROW_END + 1, ws.nrows)):
                    for col in range(PLAN_COL_START, PLAN_COL_END + 1):
                        cells.append((name, row, col))
        except Exception:
            pass
        session.check_cells(fpath, cells)
    entry = _normalize_cache_entry(_file_color_cache.get(key))
    return entry["colored"]


PLAN_COL_START = 7
PLAN_COL_END = 18
DATA_ROW_START = 9
DATA_ROW_END = 5000
