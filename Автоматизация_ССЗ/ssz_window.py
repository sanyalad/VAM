import os
import subprocess
import sys
from collections import Counter, defaultdict
from copy import copy
from datetime import datetime, timedelta, date
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.properties import WorksheetProperties, PageSetupProperties
from PyQt6.QtCore import Qt, QDate, pyqtSignal, QTimer, QElapsedTimer
from PyQt6.QtGui import QFont, QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QComboBox,
    QMessageBox,
    QAbstractItemView,
    QDialog,
    QDateEdit,
    QCheckBox,
    QTextEdit,
    QProgressBar,
    QScrollArea,
    QStyledItemDelegate,
    QCompleter,
)

from ssz_config import CONFIG, save_config
from ssz_schedule import (
    get_filtered_history,
    make_history_line,
    record_issued_tasks,
    colored_to_strings,
    count_history_in_period,
    clear_history_for_period,
    get_history_file,
    get_schedules_dir,
)
from ssz_worker import (
    ScheduleAnalysisWorker,
    BulkPipelineWorker,
    PrintWorker,
    PrinterQueueWorker,
)
from printer_utils import (
    get_target_printer,
    scan_printers_status,
)
from xls_color_cache import ExcelColorSession, release_excel_com
from ssz_safety import (
    PprSafetyError,
    build_audit_payload,
    fingerprint_matches,
    is_ppr_task,
    read_audit_sheet,
    source_coord,
    validate_ppr_tasks_for_generation,
    write_audit_sheet,
)
from operations_log import log_operation, read_log_tail
from ssz_dialogs import (
    OperationProgressDialog,
    AnalysisWarningsDialog,
    OperationsLogDialog,
    BulkSummaryDialog,
    PrintSummaryDialog,
    BulkGenDialog,
    EditableComboDelegate,
    BulkExtraTasksDialog,
    ExecutorOverrideDialog,
    HistoryResetDialog,
    AdminSettingsDialog,
)
from ssz_utils import (
    auto_correct_task,
    auto_correct_place,
    get_duty_surname,
    get_day_executors,
    get_executor,
    get_default_tasks,
    get_kip_dmm_number,
    kip_dmm_task_text,
    manual_cache_combo_lists,
)
from bulk_extra_cache import save_bulk_extra_draft, load_bulk_extra_draft, draft_info
from ssz_controller import WorkerController

TEMPLATE_FILE = "Шаблон_ССЗ.xlsx"
MANUAL_CACHE_FILE = "Кэш_доп_заданий.txt"
_template_bytes_cache = None
START_ROW = 3



def write_kip_dmm_schedule_excel(start_date, end_date):
    """График замены круговых д-мм по КИПам на каждый день периода."""
    wb = Workbook()
    ws = wb.active
    ws.title = "График д-мм"
    headers = ("Дата", "Сменный", "КИП №", "Задание", "Место")
    header_font = Font(bold=True, size=11)
    header_fill = PatternFill("solid", fgColor="D9E1F2")
    for col, title in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=title)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    row = 2
    curr = start_date
    while curr <= end_date:
        dt = datetime.combine(curr, datetime.min.time())
        kip = get_kip_dmm_number(dt)
        ws.cell(row=row, column=1, value=curr.strftime("%d.%m.%Y"))
        ws.cell(row=row, column=2, value=get_duty_surname(dt))
        ws.cell(row=row, column=3, value=kip)
        ws.cell(row=row, column=4, value=kip_dmm_task_text(kip))
        ws.cell(row=row, column=5, value=CONFIG.get("kip_dmm_place", "Цех № 47"))
        row += 1
        curr += timedelta(days=1)
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 8
    ws.column_dimensions["D"].width = 42
    ws.column_dimensions["E"].width = 14
    out_file = (
        f"График_д-мм_{start_date.strftime('%Y-%m-%d')}_"
        f"{end_date.strftime('%Y-%m-%d')}.xlsx"
    )
    wb.save(out_file)
    wb.close()
    log_operation("kip_schedule", f"saved {out_file} days={row - 2}")
    return out_file



def load_template_bytes():
    global _template_bytes_cache
    if _template_bytes_cache is None:
        with open(TEMPLATE_FILE, "rb") as f:
            _template_bytes_cache = f.read()
    return _template_bytes_cache


def write_excel_document(
    target_date,
    tasks_list,
    exec_name,
    template_bytes=None,
    stage_cb=None,
    cancel_check=None,
):
    # Формирование файла начинается только после доказанной проверки каждого ППР.
    audit_payload = build_audit_payload(target_date, tasks_list)
    ppr_counts = {}
    for task in tasks_list:
        if not is_ppr_task(task):
            continue
        executor = str(task.get("executor") or exec_name).strip()
        if not executor:
            raise ValueError("У ППР не указан исполнитель")
        key = (target_date.date() if isinstance(target_date, datetime) else target_date, executor)
        ppr_counts[key] = ppr_counts.get(key, 0) + 1
        if ppr_counts[key] > int(CONFIG.get("max_ppr_per_day", 2)):
            raise ValueError(
                f"Нельзя сформировать ССЗ: {executor} назначено "
                f"{ppr_counts[key]} ППР на {target_date.strftime('%d.%m.%Y')}"
            )
    if cancel_check and cancel_check():
        return None
    if stage_cb:
        stage_cb("шаблон")
    if template_bytes is not None:
        wb = load_workbook(BytesIO(template_bytes))
    else:
        wb = load_workbook(TEMPLATE_FILE)
    if cancel_check and cancel_check():
        wb.close()
        return None
    ws = wb.active
    styles = []
    for c in range(1, 16):
        cl = ws.cell(row=START_ROW, column=c)
        styles.append(
            {
                "f": copy(cl.font),
                "b": copy(cl.border),
                "fi": copy(cl.fill),
                "a": copy(cl.alignment),
                "nf": copy(cl.number_format),
            }
        )
    if ws.max_row > START_ROW:
        ws.delete_rows(START_ROW + 1, ws.max_row - START_ROW)
    date_str = target_date.strftime("%d.%m.%Y")
    if stage_cb:
        stage_cb("запись")
    cur_r = START_ROW
    for t in tasks_list:
        if cancel_check and cancel_check():
            wb.close()
            return None
        ws.cell(row=cur_r, column=1, value=date_str)
        ws.cell(row=cur_r, column=2, value=CONFIG.get("default_time", ""))
        ws.cell(row=cur_r, column=3, value=t["work"])
        ws.cell(row=cur_r, column=4, value=t["place"])
        ws.cell(row=cur_r, column=5, value=CONFIG.get("rules", ""))
        ws.cell(row=cur_r, column=6, value=CONFIG.get("task_issuer", ""))
        task_executor = t.get("executor")
        if not task_executor or task_executor == "Сменный":
            task_executor = exec_name
        ws.cell(row=cur_r, column=8, value=task_executor)
        for c in range(1, 16):
            target = ws.cell(row=cur_r, column=c)
            s = styles[c - 1]
            target.font, target.border = s["f"], s["b"]
            target.fill, target.alignment = s["fi"], s["a"]
            target.number_format = s["nf"]
        cur_r += 1

    write_audit_sheet(wb, audit_payload)
    
    out_dir = "Архив_ССЗ"
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    out_file = os.path.join(out_dir, f"ССЗ_{target_date.strftime('%Y-%m-%d')}.xlsx")
    temp_file = out_file + ".tmp.xlsx"
    
    if ws.sheet_properties is None:
        ws.sheet_properties = WorksheetProperties()
    if ws.sheet_properties.pageSetUpPr is None:
        ws.sheet_properties.pageSetUpPr = PageSetupProperties()
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1

    if stage_cb:
        stage_cb("сохранение")
    if cancel_check and cancel_check():
        wb.close()
        return None
    try:
        try:
            wb.save(temp_file)
        finally:
            wb.close()

        # Повторное открытие ловит повреждённый/неполный файл до замены архива.
        check_wb = load_workbook(temp_file, read_only=True, data_only=True)
        try:
            check_ws = check_wb.active
            written = 0
            for row in check_ws.iter_rows(min_row=START_ROW, values_only=True):
                if any(v not in (None, "") for v in row):
                    written += 1
            if written != len(tasks_list):
                raise IOError(
                    f"Контроль ССЗ не пройден: ожидалось строк {len(tasks_list)}, записано {written}"
                )
            if read_audit_sheet(check_wb) is None:
                raise IOError("Контроль ССЗ не пройден: паспорт безопасности не записан")
        finally:
            check_wb.close()
        # Закрываем окно гонки: график мог измениться, пока формировался файл.
        validate_ppr_tasks_for_generation(tasks_list)
        os.replace(temp_file, out_file)
        log_operation(
            "ssz_safety_manifest",
            f"file={os.path.basename(out_file)} ppr={len(audit_payload['ppr_tasks'])} status=written",
        )
    except Exception:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass
        raise
    return out_file


def validate_ssz_files_for_print(file_paths, cancel_check=None):
    """Проверяет файлы и заново читает видимый цвет исходных ячеек Excel."""
    limit = int(CONFIG.get("max_ppr_per_day", 2))
    tasks_by_source = defaultdict(list)
    for path in file_paths:
        if cancel_check and cancel_check():
            raise PprSafetyError("Проверка ССЗ перед печатью отменена")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Файл ССЗ не найден: {path}")
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.active
            counts = {}
            workbook_ppr = []
            for row in ws.iter_rows(min_row=START_ROW, values_only=True):
                work = str(row[2] or "") if len(row) > 2 else ""
                if "ППР" not in work.upper():
                    continue
                place = str(row[3] or "") if len(row) > 3 else ""
                workbook_ppr.append((" ".join(work.split()), " ".join(place.split())))
                day = str(row[0] or "")
                executor = str(row[7] or "").strip() if len(row) > 7 else ""
                if not executor:
                    raise ValueError(f"{os.path.basename(path)}: у ППР не указан исполнитель")
                key = (day, executor)
                counts[key] = counts.get(key, 0) + 1
                if counts[key] > limit:
                    raise ValueError(
                        f"{os.path.basename(path)}: {executor} назначено "
                        f"{counts[key]} ППР на {day}"
                    )

            audit = read_audit_sheet(wb)
            if workbook_ppr and audit is None:
                raise PprSafetyError(
                    f"{os.path.basename(path)}: нет паспорта проверки цветов. "
                    "Файл необходимо сформировать заново."
                )
            manifest_tasks = (audit or {}).get("ppr_tasks", [])
            manifest_ppr = [
                (
                    " ".join(str(task.get("work") or "").split()),
                    " ".join(str(task.get("place") or "").split()),
                )
                for task in manifest_tasks
            ]
            if Counter(workbook_ppr) != Counter(manifest_ppr):
                raise PprSafetyError(
                    f"{os.path.basename(path)}: ППР в файле не совпадают с паспортом проверки. "
                    "Файл необходимо сформировать заново."
                )
            for task in manifest_tasks:
                if task.get("color_state") != "uncolored" or task.get("color_source") != "excel_display_format":
                    raise PprSafetyError(
                        f"{os.path.basename(path)}: ППР не имеет подтверждённого допуска по цвету."
                    )
                expected = task.get("source_fingerprint")
                if not fingerprint_matches(expected):
                    raise PprSafetyError(
                        f"{os.path.basename(path)}: исходный график изменился после генерации. "
                        "Повторите анализ и сформируйте ССЗ заново."
                    )
                tasks_by_source[os.path.abspath(task["source_file"])].append(
                    (source_coord(task), task, path)
                )
        finally:
            wb.close()

    if tasks_by_source:
        with ExcelColorSession(force_refresh=True) as color_session:
            for source_file, entries in tasks_by_source.items():
                if cancel_check and cancel_check():
                    raise PprSafetyError("Проверка ССЗ перед печатью отменена")
                coords = {coord for coord, _task, _path in entries}
                colored = color_session.check_cells(
                    source_file, coords, cancel_check=cancel_check
                )
                if colored:
                    rejected = [task for coord, task, _path in entries if coord in colored]
                    details = "; ".join(
                        f"{task.get('source_sheet')}!{task.get('source_cell')} — {task.get('work')}"
                        for task in rejected
                    )
                    raise PprSafetyError(
                        "Печать заблокирована: после генерации обнаружены закрашенные ППР: "
                        + details
                    )
                log_operation(
                    "print_color_validation",
                    f"source={os.path.basename(source_file)} checked={len(coords)} "
                    "colored=0 status=complete",
                )
    return True


def _plan_label(task):
    plan = task.get("plan_day", task.get("original_day", "?"))
    assigned = task.get("assigned_day", plan)
    if int(assigned) != int(plan):
        return f"план {plan}-е → {assigned}-е"
    return f"{plan}-е"


# Cleaned up leftovers of delegate and worker controller.


class SszWindow(QWidget):
    go_home = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.target_date = datetime.today()
        self.assigned_ppr = []
        self.manual_tasks = []
        self.other_days_history = []
        self.cached_manual_tasks = []
        self.last_colored_skipped = []
        self.last_moved_log = []
        self.last_report = None
        self._worker_ctrl = WorkerController(self)
        self._bulk_do_print = False
        self.load_manual_cache()
        self._build_ui()

    def _build_ui(self):
        self.setFont(QFont("Segoe UI", 10))
        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(12, 8, 12, 8)

        # ─── Верхняя панель ───
        top_row = QHBoxLayout()
        btn_home = QPushButton("← На главную")
        btn_home.setObjectName("btn_secondary")
        btn_home.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_home.clicked.connect(self.go_home.emit)
        top_row.addWidget(btn_home)
        lbl_ssz = QLabel("Сменно-суточные задания (ССЗ)")
        lbl_ssz.setStyleSheet("font-weight:bold;color:#005A9E;font-size:15px;")
        top_row.addStretch()
        top_row.addWidget(lbl_ssz)
        main_layout.addLayout(top_row)

        # ─── 1. Дата задания ───
        gb_date = QGroupBox(" 1. Дата задания ")
        l_date = QHBoxLayout(gb_date)
        l_date.setContentsMargins(12, 20, 12, 10)
        l_date.addWidget(QLabel("Дата:"))
        self.ent_date = QDateEdit()
        self.ent_date.setDate(QDate(self.target_date.year, self.target_date.month, self.target_date.day))
        self.ent_date.setCalendarPopup(True)
        self.ent_date.setDisplayFormat("dd.MM.yyyy")
        self.ent_date.setFixedWidth(130)
        self._date_analysis_timer = QTimer(self)
        self._date_analysis_timer.setSingleShot(True)
        self._date_analysis_timer.setInterval(350)
        self._date_analysis_timer.timeout.connect(self._auto_analyze_date)
        self.ent_date.dateChanged.connect(self._on_date_changed)
        # ←/→ навигация по дням
        btn_prev_day = QPushButton("←")
        btn_prev_day.setFixedWidth(32)
        btn_prev_day.setFixedHeight(30)
        btn_prev_day.setToolTip("Назад на 1 день")
        btn_prev_day.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_prev_day.clicked.connect(lambda: self.ent_date.setDate(self.ent_date.date().addDays(-1)))
        btn_next_day = QPushButton("→")
        btn_next_day.setFixedWidth(32)
        btn_next_day.setFixedHeight(30)
        btn_next_day.setToolTip("Вперёд на 1 день (Ctrl+D)")
        btn_next_day.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_next_day.clicked.connect(lambda: self.ent_date.setDate(self.ent_date.date().addDays(1)))
        # Индикатор дня недели
        self.lbl_weekday = QLabel("")
        self.lbl_weekday.setFixedWidth(100)
        self.lbl_weekday.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l_date.addWidget(btn_prev_day)
        l_date.addWidget(self.ent_date)
        l_date.addWidget(btn_next_day)
        l_date.addWidget(self.lbl_weekday)
        self.lbl_quick_info = QLabel("")
        self.lbl_quick_info.setStyleSheet("color:#546E7A;font-size:10px;")
        l_date.addWidget(self.lbl_quick_info)
        l_date.addStretch()
        self.btn_analyze = QPushButton("🔄  Анализировать графики")
        self.btn_analyze.setObjectName("btn_primary")
        self.btn_analyze.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_analyze.clicked.connect(self.analyze_schedules)
        l_date.addWidget(self.btn_analyze)
        self.btn_recheck_colors = QPushButton("🎨  Перепроверить цвета")
        self.btn_recheck_colors.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_recheck_colors.clicked.connect(
            lambda _checked=False: self.analyze_schedules(force_refresh_colors=True)
        )
        l_date.addWidget(self.btn_recheck_colors)
        self.cb_redistribute = QCheckBox("Не более 2 ППР исполнителю/день")
        self.cb_redistribute.setChecked(True)
        self.cb_redistribute.setEnabled(False)
        self.cb_redistribute.setToolTip("Обязательное правило безопасности")
        l_date.addWidget(self.cb_redistribute)
        main_layout.addWidget(gb_date)
        self._update_quick_info()
        self._update_weekday_label()
        self.ent_date.dateChanged.connect(self._update_weekday_label)

        # ─── 2. Сводка по плановым ППР ───
        gb_ppr = QGroupBox(" 2. Сводка по плановым ППР ")
        l_ppr = QVBoxLayout(gb_ppr)
        l_ppr.setContentsMargins(12, 20, 12, 10)
        self.lbl_day_info = QLabel("Дежурный: —  |  Задач ППР: —")
        self.lbl_day_info.setStyleSheet("color:#005A9E;font-weight:bold;font-size:11px;")
        l_ppr.addWidget(self.lbl_day_info)
        self.table_ppr = QTableWidget(0, 4)
        self.table_ppr.setHorizontalHeaderLabels(["Задание", "Место", "План", "Исполнитель"])
        self.table_ppr.setWordWrap(True)
        self.table_ppr.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table_ppr.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_ppr.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_ppr.setAlternatingRowColors(True)
        self.table_ppr.doubleClicked.connect(lambda: self.edit_task(is_ppr=True))
        self.table_ppr.setColumnWidth(1, 140)
        self.table_ppr.setColumnWidth(2, 120)
        self.table_ppr.setColumnWidth(3, 210)
        l_ppr.addWidget(self.table_ppr)
        self.lbl_colored_info = QLabel("")
        self.lbl_colored_info.setStyleSheet("color:#D32F2F;font-weight:bold;font-size:11px;")
        self.lbl_colored_info.hide()
        l_ppr.addWidget(self.lbl_colored_info)
        l_ppr_btns = QHBoxLayout()
        self.btn_edit_ppr = QPushButton("Изменить")
        self.btn_edit_ppr.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit_ppr.clicked.connect(lambda: self.edit_task(is_ppr=True))
        self.btn_del_ppr = QPushButton("Удалить (пропустить)")
        self.btn_del_ppr.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_del_ppr.clicked.connect(self.remove_ppr)
        
        self.ppr_btns_widget = QWidget()
        l_ppr_btns = QHBoxLayout(self.ppr_btns_widget)
        l_ppr_btns.setContentsMargins(0, 0, 0, 0)
        l_ppr_btns.addStretch()
        l_ppr_btns.addWidget(self.btn_edit_ppr)
        l_ppr_btns.addWidget(self.btn_del_ppr)
        l_ppr.addWidget(self.ppr_btns_widget)
        
        main_layout.addWidget(gb_ppr)

        # ─── 3. Дополнительные задания ───
        self.gb_manual = QGroupBox(" 3. Дополнительные задания (вручную) ")
        l_manual = QVBoxLayout(self.gb_manual)
        l_manual.setContentsMargins(12, 20, 12, 10)
        l_inputs = QHBoxLayout()
        self.ent_manual_work = QComboBox()
        self.ent_manual_work.setEditable(True)
        self.ent_manual_work.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.ent_manual_work.setMinimumContentsLength(10)
        self.ent_manual_work.lineEdit().setPlaceholderText("Текст задания…")
        self.ent_manual_place = QComboBox()
        self.ent_manual_place.setEditable(True)
        self.ent_manual_place.setFixedWidth(180)
        self.ent_manual_place.lineEdit().setPlaceholderText("Место…")
        self.ent_manual_exec = QComboBox()
        self.ent_manual_exec.setEditable(True)
        self.ent_manual_exec.setFixedWidth(150)
        self.ent_manual_exec.addItems(["Сменный", "Наладчик КИПиА Дмитриев И.С.", "Наладчик КИПиА Войтов А.М."])
        self.update_comboboxes()
        
        self.ent_manual_work.lineEdit().editingFinished.connect(self._format_manual_inputs)
        self.ent_manual_place.lineEdit().editingFinished.connect(self._format_manual_inputs)
        btn_add = QPushButton("Добавить")
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.setObjectName("btn_primary")
        btn_add.clicked.connect(self.add_manual_task)
        l_inputs.addWidget(self.ent_manual_work, stretch=1)
        l_inputs.addWidget(self.ent_manual_place)
        l_inputs.addWidget(self.ent_manual_exec)
        l_inputs.addWidget(btn_add)
        l_manual.addLayout(l_inputs)
        self.table_manual = QTableWidget(0, 3)
        self.table_manual.setHorizontalHeaderLabels(["Задание", "Место", "Исполнитель"])
        self.table_manual.setWordWrap(True)
        self.table_manual.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table_manual.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_manual.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_manual.setAlternatingRowColors(True)
        self.table_manual.setColumnWidth(1, 160)
        self.table_manual.doubleClicked.connect(lambda: self.edit_task(is_ppr=False))
        l_manual.addWidget(self.table_manual)
        l_manual_btns = QHBoxLayout()
        btn_edit_manual = QPushButton("Изменить")
        btn_edit_manual.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_edit_manual.clicked.connect(lambda: self.edit_task(is_ppr=False))
        btn_del_manual = QPushButton("Удалить")
        btn_del_manual.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_del_manual.clicked.connect(self.remove_manual_task)
        l_manual_btns.addStretch()
        l_manual_btns.addWidget(btn_edit_manual)
        l_manual_btns.addWidget(btn_del_manual)
        l_manual.addLayout(l_manual_btns)
        main_layout.addWidget(self.gb_manual)

        # ─── Главные кнопки ───
        l_final_btns = QHBoxLayout()
        l_final_btns.setSpacing(10)
        self.btn_build = QPushButton("✅  СФОРМИРОВАТЬ ЭТОТ ДЕНЬ  (Ctrl+Enter)")
        self.btn_build.setObjectName("btn_success")
        self.btn_build.setFixedHeight(50)
        self.btn_build.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_build.clicked.connect(self.build_excel)
        self.btn_bulk = QPushButton("📦  МАССОВАЯ ГЕНЕРАЦИЯ")
        self.btn_bulk.setObjectName("btn_primary")
        self.btn_bulk.setFixedHeight(50)
        self.btn_bulk.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bulk.clicked.connect(self._open_bulk_extra_dialog)
        self.btn_clear_queue = QPushButton("🧹  ОЧИСТИТЬ ОЧЕРЕДЬ")
        self.btn_clear_queue.setObjectName("btn_secondary")
        self.btn_clear_queue.setFixedHeight(50)
        self.btn_clear_queue.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_queue.clicked.connect(self.clear_printer_queue)
        l_final_btns.addWidget(self.btn_build, stretch=2)
        l_final_btns.addWidget(self.btn_bulk, stretch=2)
        l_final_btns.addWidget(self.btn_clear_queue, stretch=1)
        main_layout.addLayout(l_final_btns)

        # ─── Вторичные кнопки ───
        l_secondary = QHBoxLayout()
        l_secondary.setSpacing(8)
        self.btn_reset_history = QPushButton("Сброс истории")
        self.btn_reset_history.setObjectName("btn_warning")
        self.btn_reset_history.setFixedHeight(36)
        self.btn_reset_history.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset_history.clicked.connect(self.open_reset_history_dialog)
        self.btn_ops_log = QPushButton("Журнал")
        self.btn_ops_log.setFixedHeight(36)
        self.btn_ops_log.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ops_log.clicked.connect(self.show_operations_log)
        self.btn_overrides = QPushButton("Замены сменных")
        self.btn_overrides.setFixedHeight(36)
        self.btn_overrides.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_overrides.clicked.connect(self.show_overrides)
        
        self.btn_settings = QPushButton("Настройки")
        self.btn_settings.setFixedHeight(36)
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.clicked.connect(self.show_settings)

        l_secondary.addWidget(self.btn_reset_history)
        l_secondary.addWidget(self.btn_ops_log)
        l_secondary.addWidget(self.btn_overrides)
        l_secondary.addWidget(self.btn_settings)
        main_layout.addLayout(l_secondary)

        # ─── Статусная строка ───
        status_row = QHBoxLayout()
        self.lbl_status = QLabel("Готово")
        self.lbl_status.setStyleSheet("font-size:10px;color:#546E7A;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(18)
        status_row.addWidget(self.lbl_status, stretch=1)
        status_row.addWidget(self.progress_bar, stretch=2)
        main_layout.addLayout(status_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(container)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(scroll)

        # ─── Тултипы + горячие клавиши ───
        self.btn_analyze.setToolTip("Читает графики из Excel и формирует список заданий ППР на выбранный день.")
        self.btn_recheck_colors.setToolTip(
            "Игнорирует кэш и повторно проверяет отображаемые цвета всех ППР через Excel."
        )
        self.btn_build.setToolTip("Создаёт готовый файл ССЗ только на выбранный день.")
        self.btn_bulk.setToolTip("Генерирует ССЗ на несколько дней подряд, учитывая расписание сменных и историю.")
        self.btn_clear_queue.setToolTip("Очищает застрявшие задачи в очереди печати.")
        self.btn_reset_history.setToolTip("Удаляет записи из истории ППР за выбранный период.")
        self.btn_ops_log.setToolTip("Открывает журнал последних действий (генерации, ошибки).")
        self.btn_overrides.setToolTip("Позволяет назначить другого сменного на выбранный период.")

        # ─── Горячие клавиши ───
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(self.build_excel)
        QShortcut(QKeySequence("Ctrl+D"), self).activated.connect(
            lambda: self.ent_date.setDate(self.ent_date.date().addDays(1))
        )

    def set_status(self, text, progress=None, maximum=None):
        self.lbl_status.setText(text)
        if progress is None:
            self.progress_bar.setVisible(False)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
        else:
            self.progress_bar.setVisible(True)
            if maximum is not None and maximum > 0:
                self.progress_bar.setRange(0, maximum)
                self.progress_bar.setValue(min(progress, maximum))
            else:
                self.progress_bar.setRange(0, 0)

    def set_busy(self, busy):
        for btn in (
            self.btn_analyze,
            self.btn_recheck_colors,
            self.btn_build,
            self.btn_bulk,
            self.btn_clear_queue,
            self.btn_reset_history,
            self.btn_ops_log,
            self.btn_overrides,
        ):
            btn.setEnabled(not busy)

    def _apply_redistribute_setting(self):
        CONFIG["redistribute_enabled"] = True

    def _update_weekday_label(self):
        """Обновляет плашку дня недели с цветовой подсветкой выходных."""
        if not hasattr(self, 'lbl_weekday'):
            return
        qd = self.ent_date.date()
        days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        w = qd.dayOfWeek()  # 1-7
        name = days[w - 1]
        if w >= 6:
            self.lbl_weekday.setText(f"<b>{name} (Выходной)</b>")
            self.lbl_weekday.setStyleSheet("background: #FFF3BF; color: #E67700; border-radius: 4px; padding: 2px 6px; font-size: 11px;")
        else:
            self.lbl_weekday.setText(f"<b>{name} (Рабочий)</b>")
            self.lbl_weekday.setStyleSheet("background: #E7F5FF; color: #1971C2; border-radius: 4px; padding: 2px 6px; font-size: 11px;")

    def _on_date_changed(self, qdate):
        """Обновить информацию при смене даты в виджете."""
        try:
            self.target_date = datetime(qdate.year(), qdate.month(), qdate.day())
        except Exception:
            pass
        self._update_quick_info()
        self._date_analysis_timer.start()

    def _auto_analyze_date(self):
        """Запускает анализ после завершения выбора/ввода даты."""
        if self._worker_ctrl.is_running():
            self._date_analysis_timer.start(500)
            return
        self.analyze_schedules()

    def _format_manual_inputs(self):
        try:
            w_text = self.ent_manual_work.currentText().strip()
            p_text = self.ent_manual_place.currentText().strip()
            if w_text:
                formatted_w = auto_correct_task(w_text)
                if formatted_w != w_text:
                    self.ent_manual_work.setCurrentText(formatted_w)
            if p_text:
                formatted_p = auto_correct_place(p_text)
                if formatted_p != p_text:
                    self.ent_manual_place.setCurrentText(formatted_p)
        except Exception:
            pass
        self._update_weekday_label()

    def _update_quick_info(self):
        """Показывает краткую информацию о дате: дежурный и КИП."""
        try:
            exec_name = get_executor(self.target_date)
            kip_num = get_kip_dmm_number(self.target_date)
            parts = exec_name.split()
            short_name = parts[-2] if len(parts) >= 2 and "." in parts[-1] else parts[-1] if parts else exec_name
            day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
            wd = self.target_date.weekday()
            day_name = day_names[wd]
            self.lbl_quick_info.setText(
                f"{day_name}  •  Дежурный: {short_name}  •  КИП д-мм: №{kip_num}"
            )
            self.lbl_day_info.setText(
                f"Дежурный: {exec_name}  |  Задач ППР: {len(self.assigned_ppr)}"
            )
        except Exception:
            self.lbl_quick_info.setText("")

    def _show_report_warnings(self, messages):
        if messages:
            AnalysisWarningsDialog(messages, self).exec()

    def show_operations_log(self):
        OperationsLogDialog(self).exec()

    def show_overrides(self):
        dlg = ExecutorOverrideDialog(self)
        if dlg.exec():
            CONFIG["executor_overrides"] = dlg.get_data()
            save_config(CONFIG)

    def _result_stats_line(self, result):
        stats = result.get("report_stats")
        if stats:
            from ssz_schedule import AnalysisReport
            r = AnalysisReport()
            r.stats = dict(stats)
            return r.stats_summary()
        msgs = result.get("report_messages") or []
        for m in msgs:
            if m.startswith("Графики:"):
                return m
        return None

    def _on_worker_error(self, message, title="Ошибка"):
        self.set_status("Ошибка")
        QMessageBox.critical(self, title, message[:4000])

    def closeEvent(self, event):
        if self._worker_ctrl.is_running():
            self._worker_ctrl.request_cancel()
            w = self._worker_ctrl.worker
            if w:
                w.wait(1000)
                if w.isRunning():
                    w.terminate()
                    w.wait(1000)
            release_excel_com(force_kill=True, wait_s=0.2)
        event.accept()

    def clear_printer_queue(self):
        if self._worker_ctrl.is_running():
            self._worker_ctrl.request_cancel()
            w = self._worker_ctrl.worker
            if w:
                w.wait(3000)

        worker = PrinterQueueWorker(clear_queues=False)
        self.set_busy(True)
        self.set_status("Проверка принтеров…", 0, 0)

        def on_scan_done(result):
            self.set_busy(False)
            scan = result.get("scan") or {}
            self._show_clear_queue_dialog(scan)

        def on_scan_error(msg, title="Ошибка"):
            self.set_busy(False)
            self._on_worker_error(msg, title)

        self._worker_ctrl.start(
            worker,
            "Проверка принтеров",
            on_scan_done,
            on_error=on_scan_error,
        )

    def _show_clear_queue_dialog(self, scan):
        lines = [
            f"Windows по умолчанию:\n  {scan.get('default') or '—'}",
            f"Очистка очередей (вкл. «копия 1»):\n  {scan.get('target') or '—'}",
            "",
            "Задания в очередях:",
        ]
        any_jobs = False
        for row in scan.get("rows") or []:
            if row["jobs"] > 0:
                any_jobs = True
                mark = []
                if row["is_default"]:
                    mark.append("default")
                if row["is_excel"]:
                    mark.append("Excel")
                suffix = f" [{', '.join(mark)}]" if mark else ""
                lines.append(f"  • {row['name']}: {row['jobs']}{suffix}")
        if not any_jobs:
            lines.append("  (нигде не видно — см. ниже)")

        extra = (
            "\n\nЕсли принтер всё равно печатает при пустых очередях:\n"
            "• Нажмите «Стоп»/«Отмена» на самом принтере (задания в его памяти).\n"
            "• В Windows сделайте нужный принтер (ту же «копию», что в Excel) "
            "единственным по умолчанию.\n"
            "• Удалите лишние «копия 1», «копия 2» в Параметры → Принтеры."
        )
        if (
            QMessageBox.question(
                self,
                "Очистить очереди",
                "\n".join(lines) + extra + "\n\nОчистить все связанные очереди?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            self.set_status("Готово")
            return

        worker = PrinterQueueWorker(clear_queues=True)
        self.set_busy(True)

        def on_clear_done(result):
            self.set_busy(False)
            cleared = result.get("cleared") or {}
            report_lines = [
                f"Обработано очередей: {len(cleared.get('printers', []))}",
                f"Снято заданий (всего): {cleared.get('before', 0)}",
                f"Осталось в очередях: {cleared.get('remaining', 0)}",
            ]
            for d in cleared.get("details") or []:
                if d.get("before", 0) or d.get("remaining", 0):
                    report_lines.append(
                        f"  • {d.get('printer')}: было {d.get('before', 0)}, "
                        f"осталось {d.get('remaining', 0)}"
                    )
            if cleared.get("remaining", 0) == 0:
                QMessageBox.information(
                    self,
                    "Очереди",
                    "\n".join(report_lines)
                    + "\n\nЕсли листы всё ещё идут — это память принтера, не Windows.",
                )
                self.set_status("Очереди очищены")
            else:
                QMessageBox.warning(
                    self,
                    "Очереди",
                    "\n".join(report_lines)
                    + "\n\nОстановите печать на устройстве и повторите.",
                )
                self.set_status(f"Осталось заданий: {cleared.get('remaining', 0)}")

        def on_clear_error(msg, title="Ошибка"):
            self.set_busy(False)
            self._on_worker_error(msg, title)

        self._worker_ctrl.start(
            worker,
            "Очистка очередей",
            on_clear_done,
            on_error=on_clear_error,
        )

    def open_reset_history_dialog(self):
        dlg = HistoryResetDialog(self)
        if not dlg.exec():
            return
        start = dlg.dt_start.date().toPyDate()
        end = dlg.dt_end.date().toPyDate()
        period = f"{start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}"
        n = count_history_in_period(start, end)
        if n == 0:
            QMessageBox.information(
                self,
                "Сброс истории",
                f"В периоде {period} записей в истории нет.",
            )
            return
        if (
            QMessageBox.question(
                self,
                "Подтверждение",
                f"Удалить {n} записей за период {period}?\n\n"
                "ППР за эти дни снова будут включаться в генерацию ССЗ.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            removed, kept = clear_history_for_period(start, end)
        except OSError as e:
            QMessageBox.critical(self, "Ошибка", str(e))
            return
        date_str = self.target_date.strftime("%d.%m.%Y")
        self.other_days_history, _ = get_filtered_history({date_str})
        QMessageBox.information(
            self,
            "Сброс истории",
            f"Удалено записей: {removed}\nОсталось в файле: {kept}",
        )
        self.set_status(f"История: удалено {removed} за {period}")

    def _start_print_worker(self, files, on_done):
        if not files:
            return
        files = sorted(files, key=lambda p: os.path.basename(p))
        printer = get_target_printer(query_excel=False)
        worker = PrintWorker(files, printer)

        def on_finished(result):
            if result.get("cancelled"):
                self.set_status("Отменено")
                return
            on_done(result)

        self._worker_ctrl.start(
            worker,
            "Печать",
            on_finished,
            on_error=lambda msg, t: self._on_worker_error(msg, "Ошибка печати"),
            error_title="Ошибка печати",
        )

    def load_manual_cache(self):
        try:
            from data_manager import db_load_manual_tasks
            for task in db_load_manual_tasks():
                if task not in self.cached_manual_tasks:
                    self.cached_manual_tasks.append(task)
        except Exception:
            pass

    def add_manual_task(self):
        work = auto_correct_task(self.ent_manual_work.currentText())
        place = auto_correct_place(self.ent_manual_place.currentText())
        executor = self.ent_manual_exec.currentText().strip() if hasattr(self, "ent_manual_exec") else "Сменный"
        if not work:
            return
        task = {"work": work, "place": place}
        if executor and executor != "Сменный":
            task["executor"] = executor
        self.manual_tasks.append(task)
        row = self.table_manual.rowCount()
        self.table_manual.insertRow(row)
        self.table_manual.setItem(row, 0, QTableWidgetItem(work))
        self.table_manual.setItem(row, 1, QTableWidgetItem(place))
        self.table_manual.setItem(row, 2, QTableWidgetItem(executor if executor else "Сменный"))
        self.save_to_manual_cache(work, place)

    def save_to_manual_cache(self, work, place):
        task = (work, place)
        if task in self.cached_manual_tasks:
            self.cached_manual_tasks.remove(task)
        self.cached_manual_tasks.append(task)
        try:
            from data_manager import db_save_manual_task
            db_save_manual_task(work, place)
        except Exception:
            pass
        self.update_comboboxes()

    def update_comboboxes(self):
        works, places = manual_cache_combo_lists(self.cached_manual_tasks)
        
        default_places = [
            CONFIG.get("place_1", "Цех № 47"),
            CONFIG.get("place_2", "Цеха № 2, 6, 66-2, 34/66-2, ИСМ"),
            "Цех № 47", "Цех № 6", "Цех № 2", "Цех № 66-2", "ИСМ", "КИП"
        ]
        for dp in default_places:
            if dp and dp not in places:
                places.append(dp)

        default_tasks = [
            CONFIG.get("task_1", ""),
            CONFIG.get("task_2", ""),
            "Выполнить обход и визуальный осмотр оборудования КИП.",
            "Заменить круговые д-ммы в КИПе."
        ]
        for dt in default_tasks:
            if dt and dt not in works:
                works.append(dt)

        self.ent_manual_work.clear()
        self.ent_manual_work.addItems(works)
        self.ent_manual_work.setCurrentIndex(-1)
        self.ent_manual_work.lineEdit().setText("")
        self.ent_manual_work.lineEdit().setPlaceholderText("Текст задания (автоподстановка)…")
        
        comp_work = QCompleter(works, self)
        comp_work.setFilterMode(Qt.MatchFlag.MatchContains)
        comp_work.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.ent_manual_work.setCompleter(comp_work)

        self.ent_manual_place.clear()
        self.ent_manual_place.addItems(places)
        self.ent_manual_place.setCurrentIndex(-1)
        self.ent_manual_place.lineEdit().setText("")
        self.ent_manual_place.lineEdit().setPlaceholderText("Место (автоподстановка)…")

        comp_place = QCompleter(places, self)
        comp_place.setFilterMode(Qt.MatchFlag.MatchContains)
        comp_place.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.ent_manual_place.setCompleter(comp_place)



    def suggest_tasks(self):
        if not self.cached_manual_tasks:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Рекомендации")
        l = QVBoxLayout(dlg)
        l.addWidget(QLabel("ППР нет. Частые задания из истории:"))
        seen = set()
        for w, p in reversed(self.cached_manual_tasks):
            if (w, p) in seen:
                continue
            seen.add((w, p))
            hl = QHBoxLayout()
            hl.addWidget(QLabel(f"[{p}] {w[:80]}"), stretch=1)
            btn = QPushButton("Добавить")
            btn.clicked.connect(lambda _, wk=w, pl=p, b=btn: self.add_from_suggestion(wk, pl, b))
            hl.addWidget(btn)
            l.addLayout(hl)
            if len(seen) >= 6:
                break
        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(dlg.accept)
        l.addWidget(btn_close)
        dlg.exec()

    def add_from_suggestion(self, work, place, btn):
        if any(t["work"] == work and t["place"] == place for t in self.manual_tasks):
            return
        executor = self.ent_manual_exec.currentText().strip() if hasattr(self, "ent_manual_exec") else "Сменный"
        task = {"work": work, "place": place}
        if executor and executor != "Сменный":
            task["executor"] = executor
        self.manual_tasks.append(task)
        row = self.table_manual.rowCount()
        self.table_manual.insertRow(row)
        self.table_manual.setItem(row, 0, QTableWidgetItem(work))
        self.table_manual.setItem(row, 1, QTableWidgetItem(place))
        self.table_manual.setItem(row, 2, QTableWidgetItem(executor if executor else "Сменный"))
        btn.setText("✔")
        btn.setEnabled(False)

    def analyze_schedules(self, force_refresh_colors=False):
        date_str = self.ent_date.text().strip()
        try:
            self.target_date = datetime.strptime(date_str, "%d.%m.%Y")
        except ValueError:
            QMessageBox.critical(self, "Ошибка", "Формат даты: ДД.ММ.ГГГГ")
            return
        schedules_dir = get_schedules_dir()
        if not os.path.exists(schedules_dir):
            QMessageBox.critical(self, "Ошибка", f"Папка «{schedules_dir}» не найдена.")
            return
        self._apply_redistribute_setting()
        kept, self.completed_signatures = get_filtered_history({date_str})
        self.other_days_history = kept
        self.t_month = self.target_date.month
        self.t_day = self.target_date.day
        worker = ScheduleAnalysisWorker(
            [self.t_month], self.completed_signatures, target_month=self.t_month,
            target_day=self.t_day, month_years={self.t_month: self.target_date.year},
            force_refresh_colors=force_refresh_colors,
        )

        def on_done(result):
            try:
                if result.get("cancelled"):
                    self.set_status("Отменено")
                    return
                self.last_colored_skipped = result.get("colored_skipped", [])
                self.last_moved_log = result.get("moved_log", [])
                self.assigned_ppr = result.get("assigned_ppr", [])
                exec_name = get_executor(self.target_date)
                day_staff = get_day_executors(self.target_date)
                kip_num = get_kip_dmm_number(self.target_date)
                self.lbl_day_info.setText(
                    f"👤 Сменный: {exec_name}  |  ☀ Дневные: {', '.join(day_staff) if day_staff else 'нет'}  |  "
                    f"📊 ППР: {len(self.assigned_ppr)}  |  🔧 КИП д-мм: №{kip_num}"
                )
                self.table_ppr.setRowCount(0)
                for i, ppr in enumerate(self.assigned_ppr):
                    self.table_ppr.insertRow(i)
                    self.table_ppr.setItem(i, 0, QTableWidgetItem(ppr.get("work", "")))
                    self.table_ppr.setItem(i, 1, QTableWidgetItem(ppr.get("place", "")))
                    self.table_ppr.setItem(i, 2, QTableWidgetItem(_plan_label(ppr)))
                    self.table_ppr.setItem(i, 3, QTableWidgetItem(ppr.get("executor", "")))
                day_colored = [
                    p
                    for p in self.last_colored_skipped
                    if p.get("day") == self.t_day and p.get("month") == self.t_month
                ]
                if day_colored:
                    txt = "Пропущены закрашенные:\n" + "\n".join(
                        f"{p.get('place', '')}: {str(p.get('work', ''))[:50]}" for p in day_colored[:3]
                    )
                    if len(day_colored) > 3:
                        txt += f"\n…и ещё {len(day_colored) - 3}"
                    self.lbl_colored_info.setText(txt)
                    self.lbl_colored_info.show()
                else:
                    self.lbl_colored_info.hide()

                stats_line = self._result_stats_line(result)
                self.set_status(stats_line or "Готово")

                messages = result.get("report_messages") or []
                if messages:
                    QTimer.singleShot(150, lambda: self._show_report_warnings(messages))
                elif not self.assigned_ppr:
                    QTimer.singleShot(150, self.suggest_tasks)
            except Exception as e:
                import logging
                logging.error(f"Error in analyze_schedules on_done: {e}", exc_info=True)
                self.set_status("Ошибка анализа")

        self._worker_ctrl.start(
            worker,
            (
                "Перепроверка цветов графиков"
                if force_refresh_colors
                else "Анализ графиков"
            ),
            on_done,
        )

    def _format_manual_inputs(self):
        work_le = self.ent_manual_work.lineEdit()
        if work_le:
            work_le.setText(auto_correct_task(work_le.text()))
        place_le = self.ent_manual_place.lineEdit()
        if place_le:
            place_le.setText(auto_correct_place(place_le.text()))

    def add_manual_task(self):
        work = auto_correct_task(self.ent_manual_work.currentText())
        place = auto_correct_place(self.ent_manual_place.currentText())
        executor = self.ent_manual_exec.currentText().strip() if hasattr(self, "ent_manual_exec") else "Сменный"
        if not work:
            return
        task = {"work": work, "place": place}
        if executor and executor != "Сменный":
            task["executor"] = executor
        self.manual_tasks.append(task)
        row = self.table_manual.rowCount()
        self.table_manual.insertRow(row)
        self.table_manual.setItem(row, 0, QTableWidgetItem(work))
        self.table_manual.setItem(row, 1, QTableWidgetItem(place))
        self.table_manual.setItem(row, 2, QTableWidgetItem(executor if executor else "Сменный"))
        self.save_to_manual_cache(work, place)

    def remove_ppr(self):
        row = self.table_ppr.currentRow()
        if row < 0:
            QMessageBox.information(self, "Внимание", "Выберите задачу ППР для удаления.")
            return
        w = self.table_ppr.item(row, 0).text()
        p = self.table_ppr.item(row, 1).text()
        preview = w[:80] + ("…" if len(w) > 80 else "")
        if QMessageBox.question(
            self,
            "Удалить ППР?",
            f"Убрать задачу из сегодняшнего ССЗ?\n\n{preview}\nМесто: {p}",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.assigned_ppr = [
            t for t in self.assigned_ppr if not (t["work"] == w and t["place"] == p)
        ]
        self.table_ppr.removeRow(row)

    def remove_manual_task(self):
        row = self.table_manual.currentRow()
        if row < 0:
            return
        w = self.table_manual.item(row, 0).text()
        p = self.table_manual.item(row, 1).text()
        ex_item = self.table_manual.item(row, 2) if self.table_manual.columnCount() > 2 else None
        ex = ex_item.text() if ex_item else ""
        idx_to_remove = -1
        for i, t in enumerate(self.manual_tasks):
            if t.get("work") == w and t.get("place") == p:
                t_ex = t.get("executor", "Сменный")
                if not ex or t_ex == ex or (ex == "Сменный" and not t.get("executor")):
                    idx_to_remove = i
                    break
        if idx_to_remove >= 0:
            self.manual_tasks.pop(idx_to_remove)
        elif 0 <= row < len(self.manual_tasks):
            self.manual_tasks.pop(row)
        self.table_manual.removeRow(row)

    def edit_task(self, is_ppr):
        table = self.table_ppr if is_ppr else self.table_manual
        row = table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Внимание", "Выберите задачу.")
            return
        old_work = table.item(row, 0).text()
        old_place = table.item(row, 1).text()
        self.ent_manual_work.setCurrentText(old_work)
        self.ent_manual_place.setCurrentText(old_place)
        if not is_ppr and table.columnCount() > 2:
            item_exec = table.item(row, 2)
            old_exec = item_exec.text() if item_exec else "Сменный"
            if hasattr(self, "ent_manual_exec"):
                self.ent_manual_exec.setCurrentText(old_exec)
        if is_ppr:
            self.remove_ppr()
        else:
            self.remove_manual_task()

    def build_excel(self):
        if not self.assigned_ppr and not self.manual_tasks:
            if QMessageBox.question(self, "Пусто", "Задач нет. Создать пустой бланк?") == QMessageBox.StandardButton.No:
                return
        if not os.path.exists(TEMPLATE_FILE):
            QMessageBox.critical(self, "Ошибка", f"Файл «{TEMPLATE_FILE}» не найден.")
            return
        tasks = get_default_tasks(self.target_date) + self.manual_tasks + self.assigned_ppr
        exec_name = get_executor(self.target_date)
        try:
            out_file = write_excel_document(self.target_date, tasks, exec_name)
            date_str = self.target_date.strftime("%d.%m.%Y")
            # History is no longer automatically overwritten when generating SSZ.
            # It will be updated only manually via the PPR Dashboard.
            day_colored = colored_to_strings(
                self.last_colored_skipped, month_filter=self.target_date.month
            )
            day_colored = [c for c in day_colored if c.startswith(f"[{self.target_date.day:02d}.")]
            dlg = PrintSummaryDialog(
                date_str,
                1,
                len(self.assigned_ppr),
                day_colored,
                [],
                get_target_printer(query_excel=False),
                self,
            )
            if dlg.exec() and dlg.confirmed_print():
                def after_single_print(print_result):
                    history_result = {"added": 0, "skipped": 0}
                    if out_file in (print_result.get("printed") or []):
                        history_result = record_issued_tasks(
                            [(date_str, self.assigned_ppr)]
                        )
                    if print_result.get("failed"):
                        self.set_status("Ошибка печати — неподтверждённые ППР не отмечены")
                    else:
                        self.set_status(
                            f"Печать: {len(print_result.get('printed', []))} из 1; "
                            f"ППР выдано +{history_result['added']}, "
                            f"повторно {history_result['skipped']}"
                        )
                self._start_print_worker(
                    [out_file],
                    after_single_print,
                )
            else:
                self.set_status(f"Сохранено: {out_file}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _open_bulk_extra_dialog(self):
        # We can also double check role here just in case
        if getattr(self, "role", "admin") == "shift":
            return
        
        if self._worker_ctrl.is_running():
            QMessageBox.information(
                self, "Внимание", "Дождитесь завершения текущей операции."
            )
            return
        dlg = BulkGenDialog(self)
        if not dlg.exec():
            return
        CONFIG["redistribute_enabled"] = True
        self.cb_redistribute.setChecked(True)
        start_date = dlg.dt_start.date().toPyDate()
        end_date = dlg.dt_end.date().toPyDate()
        dates = []
        curr = start_date
        while curr <= end_date:
            dates.append(datetime.combine(curr, datetime.min.time()))
            curr += timedelta(days=1)
            
        ignore_dates = {d.strftime("%d.%m.%Y") for d in dates}
        kept_history, completed_signatures = get_filtered_history(ignore_dates)
        months = sorted(set(d.month for d in dates))
        target_days = {
            month: min(d.day for d in dates if d.month == month)
            for month in months
        }

        worker = ScheduleAnalysisWorker(
            months, completed_signatures,
            month_years={d.month: d.year for d in dates},
            target_days=target_days,
            force_refresh_colors=True,
        )
        self._worker_ctrl.start(
            worker,
            "Предварительный анализ графиков ППР",
            lambda result: self._on_bulk_analysis_done(
                result, dates, start_date, end_date, dlg.cb_print.isChecked(), kept_history, ignore_dates
            ),
        )

    def _on_bulk_analysis_done(self, result, dates, start_date, end_date, do_print, kept_history, ignore_dates):
        if result.get("cancelled"):
            self.set_status("Отменено")
            return
            
        month_schedules = result.get("month_schedules", {})
        all_colored = result.get("colored_skipped", [])
        all_moved = result.get("moved_log", [])
        report_messages = result.get("report_messages", [])
        report_stats = result.get("report_stats", {})
        
        ppr_counts = {}
        for d in dates:
            assigned = month_schedules.get(d.month, {}).get(d.day, [])
            ppr_counts[d.strftime("%d.%m.%Y")] = len(assigned)
        if ppr_counts and not any(ppr_counts.values()):
            self.set_status(
                "На выбранные даты незакрашенных плановых ППР нет; "
                "задания с будущих плановых дат не переносились"
            )

        self.load_manual_cache()
        extra_dlg = BulkExtraTasksDialog(
            dates,
            self,
            self.cached_manual_tasks,
            start_date=start_date,
            end_date=end_date,
            ppr_counts=ppr_counts,
            all_colored=all_colored,
        )
        if not extra_dlg.exec():
            info = draft_info()
            if info and info.get("tasks"):
                QMessageBox.information(
                    self,
                    "Черновик сохранён",
                    "Введённые доп. задания сохранены в «Кэш_массовых_доп_заданий.json».\n"
                    "При следующей генерации на эти даты они подставятся автоматически.",
                )
            return
            
        extra_by_date = extra_dlg.get_extra_by_date()
        save_bulk_extra_draft(start_date, end_date, extra_by_date)
        for day_tasks in extra_by_date.values():
            for t in day_tasks:
                self.save_to_manual_cache(t["work"], t["place"])
                
        self._start_bulk_generation(
            dates,
            start_date,
            end_date,
            do_print,
            extra_by_date,
            month_schedules,
            all_colored,
            all_moved,
            kept_history,
            ignore_dates,
            report_messages,
            report_stats,
        )

    def _start_bulk_generation(
        self, dates, start_date, end_date, do_print, extra_tasks_by_date, month_schedules, all_colored, all_moved, kept_history, ignore_dates, report_messages, report_stats
    ):
        if not os.path.exists(TEMPLATE_FILE):
            QMessageBox.critical(self, "Ошибка", "Шаблон не найден.")
            return

        self._bulk_do_print = do_print
        worker = BulkPipelineWorker(
            dates,
            start_date,
            end_date,
            ignore_dates,
            extra_tasks_by_date=extra_tasks_by_date or {},
            month_schedules=month_schedules,
            all_colored=all_colored,
            all_moved=all_moved,
            kept_history=kept_history,
            report_messages=report_messages,
            report_stats=report_stats,
        )

        def on_done(result):
            if result.get("cancelled"):
                self.set_status("Отменено")
                info = draft_info()
                if info and info.get("tasks"):
                    QMessageBox.information(
                        self,
                        "Отменено",
                        "Массовая генерация прервана.\n\n"
                        "Доп. задания сохранены в «Кэш_массовых_доп_заданий.json» "
                        f"({info['tasks']} записей).\n"
                        "Запустите массовую генерацию снова — таблица подставится автоматически.\n\n"
                        "Проверка видимых цветов через Excel обязательна для каждого ППР.",
                    )
                return
            stats_line = self._result_stats_line(result)
            if stats_line:
                self.set_status(stats_line)
            QTimer.singleShot(0, lambda: self._on_bulk_finished(result))

        self._worker_ctrl.start(
            worker,
            "Массовая генерация",
            on_done,
        )

    def _on_bulk_finished(self, result):
        try:
            self._on_bulk_finished_impl(result)
        except Exception as e:
            import traceback

            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить черновик: {e}\n\n{traceback.format_exc()}")

    def _on_bulk_finished_impl(self, result):
        # History is no longer automatically overwritten when generating SSZ.
        self._show_report_warnings(result.get("report_messages") or [])
        period_str = (
            f"{result['start_date'].strftime('%d.%m.%Y')} — "
            f"{result['end_date'].strftime('%d.%m.%Y')}"
        )
        out_files = result.get("out_files", [])
        if len(out_files) != result.get("total_files"):
            QMessageBox.warning(
                self,
                "Проверка файлов",
                f"Ожидалось {result.get('total_files')} файлов, создано {len(out_files)}.",
            )

        def after_print(print_result):
            try:
                printed_set = set(print_result.get("printed") or [])
                ppr_map = result.get("ppr_tasks_by_file") or {}
                printed_groups = [
                    (data["date"], data.get("tasks") or [])
                    for path, data in ppr_map.items()
                    if path in printed_set
                ]
                history_result = record_issued_tasks(printed_groups)
                q = print_result.get("queue_added", 0)
                exp = print_result.get("expected", len(out_files))
                if q < exp and not print_result.get("cancelled"):
                    QMessageBox.warning(
                        self,
                        "Печать",
                        f"В очередь попало ~{q} из {exp} заданий.\n"
                        "Проверьте принтер или повторите печать.",
                    )
                if print_result.get("excel_printer_bound") is False:
                    QMessageBox.warning(
                        self,
                        "Принтер",
                        "Excel не удалось привязать к принтеру Windows по умолчанию.\n"
                        "Порядок печати может отличаться. Проверьте принтер в Excel "
                        "(Файл → Печать) и в Windows.",
                    )
                order_preview = ", ".join(
                    os.path.basename(p).replace("ССЗ_", "").replace(".xlsx", "")
                    for p in (print_result.get("printed") or [])[:5]
                )
                extra = len(print_result.get("printed") or []) - 5
                if extra > 0:
                    order_preview += f" … (+{extra})"
                self.set_status(
                    f"Печать: {len(print_result.get('printed', []))} файлов. "
                    f"ППР выдано +{history_result['added']}, "
                    f"повторно {history_result['skipped']}. "
                    f"Порядок отправки: {order_preview}"
                )
                BulkSummaryDialog(
                    result["total_files"],
                    result["total_ppr"],
                    result["colored_strings"],
                    result.get("moved_strings"),
                    self,
                    completion_result=history_result,
                ).exec()
            except Exception as e:
                import traceback
                self._on_worker_error(f"{e}\n\n{traceback.format_exc()}")

        if self._bulk_do_print:
            dlg = PrintSummaryDialog(
                period_str,
                result["total_files"],
                result["total_ppr"],
                result["colored_strings"],
                result.get("moved_strings"),
                get_target_printer(query_excel=False),
                self,
            )
            if dlg.exec() and dlg.confirmed_print():
                self._start_print_worker(out_files, after_print)
                return

        self.set_status(f"Сформировано: {result['total_files']} файлов")
        BulkSummaryDialog(
            result["total_files"],
            result["total_ppr"],
            result["colored_strings"],
            result.get("moved_strings"),
            self,
        ).exec()


    def show_settings(self):
        dlg = AdminSettingsDialog(self)
        dlg.exec()




    def _show_context_menu(self, pos):
        item = self.table_ppr.itemAt(pos) if hasattr(self, 'table_ppr') else None
        if not item:
            return

        menu = QMenu(self)
        if getattr(self, "role", "admin") == "admin":
            act_edit = menu.addAction("Изменить (временно)...")
            act_del = menu.addAction("Удалить / Игнорировать")
            menu.addSeparator()
            act_clear_day = menu.addAction("Снять отметки «Выполнено» за этот день")
            act_clear_month = menu.addAction(
                "Снять ВСЕ отметки «Выполнено» за месяц..."
            )
        else:
            act_edit = None
            act_del = None
            act_clear_day = None
            act_clear_month = None

        action = menu.exec(self.table_ppr.viewport().mapToGlobal(pos)) if hasattr(self, 'table_ppr') else None
        if not action:
            return

        if act_edit and action == act_edit:
            self.edit_task(is_ppr=True)
        elif act_del and action == act_del:
            self.remove_ppr()
        elif act_clear_day and action == act_clear_day:
            self._clear_done_for_day(item)
        elif act_clear_month and action == act_clear_month:
            self._clear_done_for_month()

    def set_role(self, role):
        self.role = role
        if role == "shift":
            self.btn_bulk.hide()
            self.btn_overrides.hide()
            self.btn_clear_queue.hide()
            self.btn_reset_history.hide()
            self.gb_manual.hide()
            self.ppr_btns_widget.hide()
        else:
            self.btn_bulk.show()
            self.btn_overrides.show()
            self.btn_clear_queue.show()
            self.btn_reset_history.show()
            self.gb_manual.show()
            self.ppr_btns_widget.show()
