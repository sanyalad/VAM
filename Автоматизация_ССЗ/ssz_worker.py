import os
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal

from ssz_config import CONFIG
from ssz_schedule import (
    fetch_month_schedules,
    get_filtered_history,
    colored_to_strings,
    moved_to_strings,
    make_history_line,
    AnalysisReport,
    schedules_need_com_excel,
)
from xls_color_cache import ExcelColorSession, release_excel_com
from operations_log import log_operation


class _CancellableThread(QThread):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cancelled = False
        self._color_session = None
        self._abort_triggered = False

    def cancel(self):
        """Запрос отмены — только флаг; taskkill выполняет воркер один раз."""
        self._cancelled = True
        self.requestInterruption()
        self._abort_excel_if_needed()

    def _abort_excel_if_needed(self):
        if self._abort_triggered:
            return
        self._abort_triggered = True
        if not CONFIG.get("excel_force_kill_on_cancel", True):
            return
        if self._color_session is not None:
            self._color_session.abort()
        else:
            release_excel_com(force_kill=True, wait_s=0.2)

    def _cancel_check(self):
        return self._cancelled or self.isInterruptionRequested()


def _run_graphs_phase(worker, months, completed_signatures, report, make_file_cb):
    """Фаза чтения графиков с ленивым Excel COM."""
    if schedules_need_com_excel():
        force_refresh = bool(getattr(worker, "force_refresh_colors", False))
        log_operation(
            "com_session",
            f"start ExcelColorSession force_refresh={force_refresh}",
        )
        with ExcelColorSession(force_refresh=force_refresh) as color_session:
            worker._color_session = color_session
            result = _run_graphs_inner(
                worker, months, completed_signatures, report, make_file_cb, color_session
            )
            worker._color_session = None
            return result
    log_operation("com_session", "skipped (no .xls / xlsx COM disabled)")
    return _run_graphs_inner(
        worker, months, completed_signatures, report, make_file_cb, None
    )

def _run_graphs_inner(worker, months, completed_signatures, report, make_file_cb, color_session):
    month_schedules = {}
    all_colored = []
    all_moved = []
    for i, m in enumerate(months, 1):
        if worker._cancel_check():
            return None
        file_cb = make_file_cb(m, i) if make_file_cb else None
        
        target_day = getattr(worker, "target_days", {}).get(m, 1)
        if getattr(worker, "target_month", None) == m and getattr(worker, "target_day", None) is not None:
            target_day = worker.target_day

        t_year = getattr(worker, "month_years", {}).get(m)
        sch, colored, moved = fetch_month_schedules(
            m,
            completed_signatures,
            report=report,
            color_session=color_session,
            cancel_check=worker._cancel_check,
            progress_cb=file_cb,
            target_day=target_day,
            t_year=t_year,
        )
        if worker._cancel_check():
            return None
        month_schedules[m] = sch
        all_colored.extend(colored)
        all_moved.extend(moved)
    return month_schedules, all_colored, all_moved


class ScheduleAnalysisWorker(_CancellableThread):
    progress = pyqtSignal(str, int, int)
    finished_ok = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(
        self,
        months,
        completed_signatures,
        target_month=None,
        target_day=None,
        month_years=None,
        force_refresh_colors=True,
        target_days=None,
    ):
        super().__init__()
        self.months = months
        self.completed_signatures = completed_signatures
        self.target_month = target_month
        self.target_day = target_day
        self.month_years = month_years or {}
        self.force_refresh_colors = bool(force_refresh_colors)
        self.target_days = {
            int(month): int(day) for month, day in (target_days or {}).items()
        }

    def run(self):
        t0 = datetime.now()
        try:
            report = AnalysisReport()
            total = len(self.months)

            def file_cb(fi, ft, msg, mi=1, tot=total, month=self.months[0]):
                self.progress.emit(
                    f"М{month} ({mi}/{tot}): {msg}", fi, max(ft, 1)
                )

            def make_file_cb(m, mi):
                def cb(fi, ft, msg):
                    file_cb(fi, ft, msg, mi=mi, tot=total, month=m)
                return cb

            graphs = _run_graphs_phase(
                self, self.months, self.completed_signatures, report, make_file_cb
            )
            if graphs is None or self._cancel_check():
                result = {
                    "month_schedules": {},
                    "colored_skipped": [],
                    "moved_log": [],
                    "report_messages": report.all_messages(),
                    "report_stats": report.stats,
                    "cancelled": True,
                }
                self.finished_ok.emit(result)
                return
            month_schedules, all_colored, all_moved = graphs

            result = {
                "month_schedules": month_schedules,
                "colored_skipped": all_colored,
                "moved_log": all_moved,
                "report_messages": report.all_messages(),
                "report_stats": report.stats,
                "cancelled": self._cancelled or self.isInterruptionRequested(),
            }
            if self.target_month and self.target_day:
                sch = month_schedules.get(self.target_month, {})
                result["assigned_ppr"] = sch.get(self.target_day, [])
            log_operation(
                "done",
                f"ScheduleAnalysisWorker cancelled={result['cancelled']} "
                f"elapsed={(datetime.now() - t0).total_seconds():.1f}s",
            )
            self.finished_ok.emit(result)
        except Exception as e:
            import traceback
            log_operation("error", f"ScheduleAnalysisWorker {e}")
            self.error.emit(f"{e}\n\n{traceback.format_exc()}")


class BulkPipelineWorker(_CancellableThread):
    """Загрузка графиков + генерация файлов в одном фоновом потоке."""

    progress = pyqtSignal(str, int, int)
    finished_ok = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, dates, start_date, end_date, ignore_dates, extra_tasks_by_date=None, month_schedules=None, all_colored=None, all_moved=None, kept_history=None, report_messages=None, report_stats=None):
        super().__init__()
        self.dates = dates
        self.start_date = start_date
        self.end_date = end_date
        self.ignore_dates = ignore_dates
        self.extra_tasks_by_date = extra_tasks_by_date or {}
        self.month_schedules = month_schedules or {}
        self.all_colored = all_colored or []
        self.all_moved = all_moved or []
        self.kept_history = kept_history or []
        self.report_messages = report_messages or []
        self.report_stats = report_stats or {}

    def run(self):
        log_operation("start", f"BulkPipelineWorker days={len(self.dates)}")
        t0 = datetime.now()
        try:
            from ssz_window import (
                get_default_tasks,
                get_executor,
                write_excel_document,
                load_template_bytes,
            )

            template_bytes = load_template_bytes()
            out_files = []
            ppr_tasks_by_file = {}
            total_ppr = 0
            kept = list(self.kept_history)
            total_days = len(self.dates)
            self.progress.emit(
                f"[2/2] Формирование ССЗ (0/{total_days})…", 0, max(total_days, 1)
            )

            for i, d in enumerate(self.dates, 1):
                if self._cancel_check():
                    self.finished_ok.emit(
                        {"cancelled": True, "partial_files": out_files}
                    )
                    return
                d_str = d.strftime("%d.%m.%Y")

                def stage_cb(stage, day_i=i, day_total=total_days, ds=d_str):
                    self.progress.emit(
                        f"[2/2] {ds} ({day_i}/{day_total}): {stage}…",
                        day_i,
                        day_total,
                    )

                self.progress.emit(f"[2/2] Формирую {d_str}…", i, total_days)
                assigned = self.month_schedules.get(d.month, {}).get(d.day, [])
                total_ppr += len(assigned)
                extra = self.extra_tasks_by_date.get(d_str, [])
                tasks = get_default_tasks(d) + extra + assigned
                out_file = write_excel_document(
                    d,
                    tasks,
                    get_executor(d),
                    template_bytes=template_bytes,
                    stage_cb=stage_cb,
                    cancel_check=self._cancel_check,
                )
                if out_file is None:
                    self.finished_ok.emit(
                        {"cancelled": True, "partial_files": out_files}
                    )
                    return
                out_files.append(out_file)
                ppr_tasks_by_file[out_file] = {
                    "date": d_str,
                    "tasks": [dict(t) for t in assigned],
                }

            dates_set = {(d.day, d.month) for d in self.dates}
            period_colored = [
                p for p in self.all_colored if (p["day"], p["month"]) in dates_set
            ]
            moved_strings = []
            months = sorted(set(d.month for d in self.dates))
            for m in months:
                moved_strings.extend(
                    moved_to_strings([x for x in self.all_moved if x.get("month") == m], m)
                )

            self.finished_ok.emit(
                {
                    "out_files": out_files,
                    "ppr_tasks_by_file": ppr_tasks_by_file,
                    "kept_history": kept,
                    "total_files": total_days,
                    "total_ppr": total_ppr,
                    "colored_strings": colored_to_strings(period_colored),
                    "moved_strings": moved_strings,
                    "start_date": self.start_date,
                    "end_date": self.end_date,
                    "report_messages": self.report_messages,
                    "report_stats": self.report_stats,
                    "cancelled": False,
                }
            )
            log_operation(
                "done",
                f"BulkPipelineWorker files={total_days} "
                f"elapsed={(datetime.now() - t0).total_seconds():.1f}s",
            )
        except Exception as e:
            import traceback
            log_operation("error", f"BulkPipelineWorker {e}")
            self.error.emit(f"{e}\n\n{traceback.format_exc()}")


class PrintWorker(_CancellableThread):
    progress = pyqtSignal(str, int, int)
    finished_ok = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, file_paths, printer_name=None):
        super().__init__()
        self.file_paths = file_paths
        self.printer_name = printer_name

    def run(self):
        log_operation("start", f"PrintWorker files={len(self.file_paths)}")
        t0 = datetime.now()
        try:
            from printer_utils import print_files_batch, get_target_printer
            from ssz_window import validate_ssz_files_for_print

            printer = self.printer_name or get_target_printer(query_excel=False)
            total = len(self.file_paths)

            def progress_cb(i, tot, msg):
                self.progress.emit(msg, i, tot)

            self.progress.emit(
                "Контроль графиков и повторная проверка цветов Excel…",
                0,
                max(total, 1),
            )
            validate_ssz_files_for_print(
                self.file_paths, cancel_check=self._cancel_check
            )
            if self._cancel_check():
                self.finished_ok.emit({"cancelled": True, "printed": []})
                return

            result = print_files_batch(
                self.file_paths,
                printer_name=printer,
                cancel_check=self._cancel_check,
                progress_cb=progress_cb,
                prep_kill_excel=False,
            )
            if self._cancel_check():
                result["cancelled"] = True
            
            log_operation(
                "done",
                f"PrintWorker cancelled={result.get('cancelled')} "
                f"elapsed={(datetime.now() - t0).total_seconds():.1f}s",
            )
            self.finished_ok.emit(result)
        except Exception as e:
            if self._cancel_check():
                self.finished_ok.emit({"cancelled": True, "printed": []})
                return
            import traceback
            log_operation("error", f"PrintWorker {e}")
            self.error.emit(f"{e}\n\n{traceback.format_exc()}")


class PrinterQueueWorker(QThread):
    """Сканирование и очистка очередей печати без блокировки UI."""

    progress = pyqtSignal(str, int, int)
    finished_ok = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, clear_queues=False):
        super().__init__()
        self.clear_queues = clear_queues

    def run(self):
        try:
            from printer_utils import scan_printers_status, clear_all_relevant_queues

            self.progress.emit("Проверка принтеров…", 0, 0)
            scan = scan_printers_status(query_excel=False)
            if not self.clear_queues:
                self.finished_ok.emit({"scan": scan, "cleared": None})
                return

            self.progress.emit("Очистка очередей…", 0, 0)
            result = clear_all_relevant_queues()
            self.finished_ok.emit({"scan": scan, "cleared": result})
        except Exception as e:
            import traceback
            self.error.emit(f"{e}\n\n{traceback.format_exc()}")
