"""Работа с очередью печати Windows (win32print) и пакетная печать Excel."""

import os
import re
import time
import threading

_print_lock = threading.Lock()


def _com_init():
    try:
        import pythoncom
        try:
            pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
        except Exception:
            pythoncom.CoInitialize()
        return True
    except Exception:
        return False


def _com_uninit():
    try:
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


def get_default_printer():
    try:
        import win32print
        return win32print.GetDefaultPrinter()
    except Exception:
        return ""


def list_installed_printers():
    try:
        import win32print

        flags = (
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        )
        raw = win32print.EnumPrinters(flags, None, 1) or []
        return [item[2] for item in raw if len(item) > 2 and item[2]]
    except Exception:
        return []


def _printer_base_key(name):
    if not name:
        return ""
    s = name.lower().strip()
    s = re.split(r"\s+on\s+", s, maxsplit=1, flags=re.I)[0]
    s = re.sub(r"\s*\(копия\s*\d*\)", "", s, flags=re.I)
    s = re.sub(r"\s*\(copy\s*\d*\)", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def find_related_printer_names(anchor_name, installed=None):
    """Все очереди той же модели: «…» и «… (копия 1)»."""
    installed = installed or list_installed_printers()
    if not anchor_name:
        return list(installed)
    key = _printer_base_key(anchor_name)
    related = []
    for p in installed:
        pk = _printer_base_key(p)
        if key and (pk == key or key in pk or pk in key):
            related.append(p)
    if anchor_name not in related:
        related.insert(0, anchor_name)
    return related or [anchor_name]


def get_excel_printer_info():
    """
    Принтер Excel (открывает Excel). Только когда нет фоновых воркеров с COM.
    """
    from xls_color_cache import _excel_lock, _com_init, _com_uninit, _safe_excel_quit

    result = {"active": "", "windows_name": "", "error": ""}
    com_ok = _com_init()
    try:
        import win32com.client

        with _excel_lock:
            xl = win32com.client.DispatchEx("Excel.Application")
            xl.Visible = False
            xl.DisplayAlerts = False
            try:
                active = str(xl.ActivePrinter)
                result["active"] = active
                installed = list_installed_printers()
                port_name = active.split(" on ")[0].strip()
                port = port_name.lower()
                for p in installed:
                    if p.lower() == port or port_name.lower() in p.lower():
                        result["windows_name"] = p
                        break
                best = result["windows_name"] or None
                best_score = -1 if not best else 999
                for p in installed:
                    pl = p.lower()
                    score = 0
                    if port and port in pl:
                        score += 10
                    if _printer_base_key(p) == _printer_base_key(port):
                        score += 8
                    jobs = count_print_jobs(p)
                    if jobs:
                        score += 5 + min(jobs, 20)
                    if score > best_score:
                        best_score = score
                        best = p
                for i in range(1, int(xl.Printers.Count) + 1):
                    pn = str(xl.Printers(i).Name)
                    if active.lower() in pn.lower() or pn.lower() in active.lower():
                        for p in installed:
                            if (
                                _printer_base_key(pn) == _printer_base_key(p)
                                or pn.split(" on ")[0].lower() in p.lower()
                            ):
                                best = p
                                break
                result["windows_name"] = best or ""
            finally:
                _safe_excel_quit(xl)
                xl = None
                import gc
                gc.collect()
    except Exception as e:
        result["error"] = str(e)
    finally:
        if com_ok:
            _com_uninit()
    return result


def get_target_printer(query_excel=False):
    """
    Принтер для печати без запуска Excel (по умолчанию).
    query_excel=True — один раз открыть Excel (только с UI, не из потока печати).
    """
    if query_excel:
        excel = get_excel_printer_info()
        if excel.get("windows_name"):
            return excel["windows_name"]

    default = get_default_printer()
    related = find_related_printer_names(default)
    for p in related:
        pl = p.lower()
        if "копия 1" in pl or "copy 1" in pl:
            return p
    for p in related:
        if count_print_jobs(p) > 0:
            return p
    return default


def scan_printers_status(query_excel=False):
    installed = list_installed_printers()
    default = get_default_printer()
    excel = (
        get_excel_printer_info()
        if query_excel
        else {"active": "", "windows_name": "", "error": ""}
    )
    target = get_target_printer(query_excel=False)
    excel_win = excel.get("windows_name") or ""
    rows = []
    for name in installed:
        rows.append(
            {
                "name": name,
                "jobs": count_print_jobs(name),
                "is_default": name == default,
                "is_excel": name == excel_win
                or (
                    excel_win
                    and _printer_base_key(name) == _printer_base_key(excel_win)
                ),
                "is_target": name == target,
            }
        )
    rows.sort(key=lambda r: (-r["jobs"], r["name"]))
    return {
        "rows": rows,
        "default": default,
        "excel_active": excel.get("active") or "",
        "excel_windows": excel_win,
        "target": target,
    }


def clear_all_relevant_queues():
    """
    Очистка: принтер Excel, Windows default, все «копии» модели, очереди с заданиями.
    """
    installed = list_installed_printers()
    default = get_default_printer()
    target = get_target_printer(query_excel=False)
    names = set()
    for seed in (target, default):
        if seed:
            names.update(find_related_printer_names(seed, installed))
    for p in installed:
        if count_print_jobs(p) > 0:
            names.add(p)
    if not names:
        if target:
            names.add(target)
        elif default:
            names.add(default)

    details = []
    total_before = 0
    total_remaining = 0
    for name in sorted(names):
        if not name:
            continue
        r = clear_print_queue(name)
        details.append(r)
        total_before += max(0, r.get("before", 0))
        total_remaining += max(0, r.get("remaining", 0))

    return {
        "ok": total_remaining == 0,
        "printers": sorted(names),
        "details": details,
        "before": total_before,
        "remaining": total_remaining,
        "target": target,
        "default": default,
        "excel_active": "",
        "excel_windows": "",
    }


def list_print_jobs(printer_name=None):
    try:
        import win32print
        name = printer_name or get_default_printer()
        if not name:
            return []
        handle = win32print.OpenPrinter(name)
        try:
            jobs = win32print.EnumJobs(handle, 0, 999, 1)
            return list(jobs) if jobs else []
        finally:
            win32print.ClosePrinter(handle)
    except Exception:
        return []


def count_print_jobs(printer_name=None):
    return len(list_print_jobs(printer_name))


def _job_has_document_hint(printer_name, hint):
    if not hint:
        return False
    h = hint.lower()
    for job in list_print_jobs(printer_name):
        doc = (job.get("pDocument") or "").lower()
        if h in doc:
            return True
    return False


def _bind_excel_printer(excel, windows_printer_name):
    """Excel часто печатает не на системный принтер по умолчанию — выравниваем."""
    if not windows_printer_name or excel is None:
        return False
    try:
        target = windows_printer_name.lower()
        for i in range(1, int(excel.Printers.Count) + 1):
            p = excel.Printers(i)
            name = str(p.Name)
            if target in name.lower() or name.lower() in target:
                excel.ActivePrinter = name
                return True
    except Exception:
        pass
    return False


def _wait_print_job_finished(
    printer_name,
    file_basename,
    before_count,
    timeout=300.0,
    cancel_check=None,
):
    """
    Ждёт цикл задания в очереди Windows: появилось → исчезло.
    Надёжнее, чем только счётчик, когда Excel отдаёт задания пачкой.
    """
    appear_deadline = time.time() + 20.0
    appeared = False
    while time.time() < appear_deadline:
        if cancel_check and cancel_check():
            return False
        if _job_has_document_hint(printer_name, file_basename):
            appeared = True
            break
        if count_print_jobs(printer_name) > before_count:
            appeared = True
            break
        time.sleep(0.25)

    # A queue which remains empty is not a successful print.  The previous
    # implementation treated it as success after the appearance timeout,
    # which made the UI report a printed SSZ even when Excel had not handed
    # the job to Windows at all.
    if not appeared:
        return False

    gone_deadline = time.time() + timeout
    while time.time() < gone_deadline:
        if cancel_check and cancel_check():
            return False
        cur = count_print_jobs(printer_name)
        if cur <= before_count and not _job_has_document_hint(
            printer_name, file_basename
        ):
            return True
        if appeared and cur <= before_count:
            return True
        time.sleep(0.5)
    return False


def _open_printer_handle(name):
    import win32print

    access = (
        win32print.PRINTER_ACCESS_ADMINISTER | win32print.PRINTER_ACCESS_USE
    )
    try:
        return win32print.OpenPrinter(name, {"DesiredAccess": access})
    except Exception:
        return win32print.OpenPrinter(name)


def _enum_jobs_on_handle(handle):
    import win32print

    return list(win32print.EnumJobs(handle, 0, 999, 1) or [])


def _cancel_jobs_on_handle(handle):
    import win32print

    n = 0
    for job in _enum_jobs_on_handle(handle):
        jid = job["JobId"]
        for cmd in (
            win32print.JOB_CONTROL_CANCEL,
            win32print.JOB_CONTROL_DELETE,
        ):
            try:
                win32print.SetJob(handle, jid, 0, None, cmd)
                n += 1
                break
            except Exception:
                continue
    return n


def clear_print_queue(printer_name=None):
    """
    Очистка очереди: PURGE + несколько проходов CANCEL/DELETE.
    Возвращает dict: ok, printer, before, remaining, error.
    """
    try:
        import win32print

        name = printer_name or get_default_printer()
        if not name:
            return {
                "ok": False,
                "printer": "",
                "before": 0,
                "remaining": 0,
                "error": "Принтер по умолчанию не задан в Windows.",
            }

        handle = _open_printer_handle(name)
        try:
            before = len(_enum_jobs_on_handle(handle))
            try:
                win32print.SetPrinter(
                    handle, 0, None, win32print.PRINTER_CONTROL_PURGE
                )
            except Exception:
                pass

            for _ in range(10):
                jobs = _enum_jobs_on_handle(handle)
                if not jobs:
                    break
                _cancel_jobs_on_handle(handle)
                time.sleep(0.35)

            remaining = len(_enum_jobs_on_handle(handle))
        finally:
            win32print.ClosePrinter(handle)

        return {
            "ok": remaining == 0,
            "printer": name,
            "before": before,
            "remaining": remaining,
            "error": "",
        }
    except Exception as e:
        return {
            "ok": False,
            "printer": printer_name or "",
            "before": -1,
            "remaining": -1,
            "error": str(e),
        }


def format_print_jobs_preview(printer_name=None, limit=5):
    jobs = list_print_jobs(printer_name)
    lines = []
    for job in jobs[:limit]:
        doc = job.get("pDocument") or "без имени"
        status = job.get("Status", 0)
        lines.append(doc if not status else f"{doc} (статус {status})")
    if len(jobs) > limit:
        lines.append(f"… и ещё {len(jobs) - limit}")
    return lines, len(jobs)


def _wait_for_queue_growth(printer_name, baseline_count, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if count_print_jobs(printer_name) > baseline_count:
            return True
        time.sleep(0.3)
    return False


def _wait_for_queue_at_most(
    printer_name, max_count, timeout=300.0, cancel_check=None
):
    """Ждёт, пока в очереди не останется не больше max_count заданий (предыдущее снято)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cancel_check and cancel_check():
            return False
        if count_print_jobs(printer_name) <= max_count:
            return True
        time.sleep(0.5)
    return False


def _create_print_excel(printer_name):
    from xls_color_cache import _com_init, _com_uninit, _excel_lock, _safe_excel_quit

    com_ok = _com_init()
    excel = None
    try:
        import win32com.client

        with _excel_lock:
            excel = win32com.client.DispatchEx("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False
            excel.ScreenUpdating = False
            _bind_excel_printer(excel, printer_name)
    except Exception:
        if excel is not None:
            _safe_excel_quit(excel)
        excel = None
        if com_ok:
            _com_uninit()
        com_ok = False
    return excel, com_ok


def print_files_batch(
    file_paths,
    printer_name=None,
    cancel_check=None,
    progress_cb=None,
    pause_between=0.2,
    prep_kill_excel=False,
):
    """
    Печать файлов последовательно. progress_cb(i, total, message).
    Возвращает dict: printed, failed, queue_added, cancelled.
    """
    from ssz_config import CONFIG
    from xls_color_cache import release_excel_com, _com_uninit, _excel_lock, _safe_excel_quit

    if not printer_name:
        printer_name = get_target_printer(query_excel=False)
    printer = printer_name
    total = len(file_paths)
    printed = []
    queue_confirmed = []
    failed = []
    cancelled = False
    job_timeout = float(CONFIG.get("print_job_timeout_s", 30))

    # Never terminate all EXCEL.EXE processes here: they may belong to the
    # user and killing them can corrupt an unrelated workbook.  Each print
    # batch owns and closes only the DispatchEx instance it created.
    if prep_kill_excel:
        release_excel_com(force_kill=False, wait_s=0.3)

    try:
        import win32com.client
        use_com = True
    except ImportError:
        use_com = False

    excel = None
    com_ok = False
    excel_printer_bound = False
    if use_com:
        excel, com_ok = _create_print_excel(printer)
        use_com = excel is not None
        excel_printer_bound = bool(excel and _bind_excel_printer(excel, printer))

    baseline = count_print_jobs(printer)

    try:
        for i, path in enumerate(file_paths, 1):
            if cancel_check and cancel_check():
                cancelled = True
                break
            abs_path = os.path.abspath(path)
            if not os.path.isfile(abs_path):
                failed.append((path, "файл не найден"))
                continue
            name = os.path.basename(path)
            if progress_cb:
                progress_cb(i, total, f"Печать {i} из {total}: {name}")

            before = count_print_jobs(printer)
            ok = False
            if use_com and excel is not None:
                try:
                    with _excel_lock:
                        wb = excel.Workbooks.Open(abs_path)
                        try:
                            try:
                                ws = wb.ActiveSheet
                                ws.PageSetup.Zoom = False
                                ws.PageSetup.FitToPagesWide = 1
                                ws.PageSetup.FitToPagesTall = 1
                            except Exception:
                                pass
                            
                            try:
                                wb.PrintOut(Copies=1)
                            except TypeError:
                                wb.PrintOut()
                        finally:
                            wb.Close(SaveChanges=False)
                    ok = True
                except Exception as e:
                    failed.append((path, str(e)))
                    _safe_excel_quit(excel)
                    excel = None
                    if com_ok:
                        _com_uninit()
                        com_ok = False
                    excel, com_ok = _create_print_excel(printer)
                    use_com = excel is not None
                    if excel:
                        excel_printer_bound = _bind_excel_printer(excel, printer)
            else:
                try:
                    os.startfile(abs_path, "print")
                    ok = True
                except Exception as e:
                    failed.append((path, str(e)))

            if ok:
                job_confirmed = _wait_print_job_finished(
                    printer,
                    name,
                    before,
                    timeout=job_timeout,
                    cancel_check=cancel_check,
                )
                if job_confirmed:
                    printed.append(path)
                    queue_confirmed.append(path)
                elif not (cancel_check and cancel_check()):
                    failed.append((path, "задание не подтверждено очередью печати"))
                if pause_between > 0:
                    time.sleep(pause_between)
    finally:
        _safe_excel_quit(excel)
        excel = None
        import gc
        gc.collect()
        if com_ok:
            _com_uninit()
        release_excel_com(force_kill=False, wait_s=0.3)

    # Jobs may leave a fast local queue before the final count is read.  The
    # reliable signal is that a job was observed for each source file.
    queue_added = len(queue_confirmed)

    return {
        "printed": printed,
        "failed": failed,
        "queue_added": queue_added,
        "queue_confirmed": queue_confirmed,
        "cancelled": cancelled,
        "expected": total,
        "printer": printer,
        "excel_printer_bound": excel_printer_bound,
    }
