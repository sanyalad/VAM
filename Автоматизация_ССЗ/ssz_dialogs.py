import os
import sys
import subprocess
import calendar
from datetime import datetime, date, timedelta

from PyQt6.QtCore import Qt, QDate, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QMessageBox,
    QCheckBox,
    QComboBox,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QGroupBox,
    QScrollArea,
    QWidget,
    QLineEdit,
    QFormLayout,
    QDateEdit,
    QTabWidget,
    QSpinBox,
    QAbstractItemView,
    QSplitter,
    QFrame,
    QGridLayout,
)

from ssz_config import CONFIG, run_system_diagnostics, save_config, validate_config
from ssz_schedule import (
    get_history_file,
    get_schedules_dir,
)
from printer_utils import (
    scan_printers_status,
)
from operations_log import read_log_tail
from bulk_extra_cache import save_bulk_extra_draft, load_bulk_extra_draft
from ssz_utils import (
    auto_correct_task,
    auto_correct_place,
    get_duty_surname,
    manual_cache_combo_lists,
)



# ═══════════════════════════════════════════════════════════════════════════
#  Dialog Classes
# ═══════════════════════════════════════════════════════════════════════════

class OperationProgressDialog(QDialog):
    cancelled = pyqtSignal()

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.resize(480, 130)
        layout = QVBoxLayout(self)
        self.lbl = QLabel("Подождите…")
        layout.addWidget(self.lbl)
        self.bar = QProgressBar()
        self.bar.setTextVisible(True)
        layout.addWidget(self.bar)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_cancel = QPushButton("Отменить")
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)
        self._done = False

    def _on_cancel(self):
        self.btn_cancel.setEnabled(False)
        self.lbl.setText("Отмена…")
        self.cancelled.emit()

    def update_progress(self, message, current, total):
        self.lbl.setText(message)
        if total <= 0:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, total)
            self.bar.setValue(min(max(current, 0), total))

    def finish(self):
        self._done = True
        self.btn_cancel.setEnabled(False)


class AnalysisWarningsDialog(QDialog):
    def __init__(self, messages, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Предупреждения анализа")
        self.resize(520, 320)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Обнаружены проблемы при чтении графиков (работа продолжена):")
        )
        te = QTextEdit()
        te.setReadOnly(True)
        te.setText("\n".join(messages))
        layout.addWidget(te)
        btn = QPushButton("Понятно")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)


class OperationsLogDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Журнал операций")
        self.resize(640, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Последние записи operations.log:"))
        te = QTextEdit()
        te.setReadOnly(True)
        te.setFont(QFont("Consolas", 9))
        te.setText(read_log_tail(120))
        layout.addWidget(te)
        btn = QPushButton("Закрыть")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)


class BulkSummaryDialog(QDialog):
    def __init__(
        self,
        total_files,
        total_ppr,
        colored_skipped_strs,
        moved_strs=None,
        parent=None,
        completion_result=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Отчет о генерации")
        self.resize(580, 480)
        layout = QVBoxLayout(self)
        lbl_title = QLabel("Массовая генерация успешно завершена!")
        lbl_title.setStyleSheet("font-weight: bold; font-size: 15px; color: #217346;")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)
        layout.addWidget(QLabel(f"Сформировано файлов (дней): {total_files}"))
        layout.addWidget(QLabel(f"Плановых ППР распределено: {total_ppr}"))
        if completion_result is not None:
            layout.addWidget(
                QLabel(
                    f"Автоматически отмечено выданными: "
                    f"{completion_result.get('added', 0)}; "
                    f"повторных ППР без дублей: {completion_result.get('skipped', 0)}"
                )
            )

        if colored_skipped_strs:
            layout.addWidget(
                QLabel(
                    f"Пропущено закрашенных (отменённых): {len(colored_skipped_strs)}"
                )
            )
            te = QTextEdit()
            te.setReadOnly(True)
            te.setText("\n".join(colored_skipped_strs))
            te.setMaximumHeight(120)
            te.setStyleSheet("background:#FFF0F0;color:#D32F2F;font-size:11px;")
            layout.addWidget(te)
        else:
            layout.addWidget(QLabel("Закрашенных (розовых) задач не обнаружено."))

        moved_strs = moved_strs or []
        if moved_strs:
            layout.addWidget(QLabel(f"Переносов/резервных назначений: {len(moved_strs)}"))
            tm = QTextEdit()
            tm.setReadOnly(True)
            tm.setText("\n".join(moved_strs[:30]))
            if len(moved_strs) > 30:
                tm.append(f"…и ещё {len(moved_strs) - 30}")
            tm.setMaximumHeight(100)
            layout.addWidget(tm)

        btn_open = QPushButton("Открыть папку с файлами")
        btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open.clicked.connect(self._open_folder)
        layout.addWidget(btn_open)
        btn_ok = QPushButton("Отлично")
        btn_ok.setObjectName("btn_success")
        btn_ok.setFixedHeight(44)
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.clicked.connect(self.accept)
        layout.addWidget(btn_ok)

    def _open_folder(self):
        folder = os.path.abspath(".")
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            subprocess.Popen(["xdg-open", folder])


class PrintSummaryDialog(QDialog):
    def __init__(
        self,
        period_str,
        total_files,
        total_ppr,
        colored_strings,
        moved_strings,
        printer_name,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Сводка перед печатью")
        self.resize(480, 380)
        self._confirmed_print = False
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Проверьте сводку перед печатью:"))
        lines = [
            f"Период: {period_str}",
            f"Будет отправлено файлов: {total_files}",
            f"Плановых ППР: {total_ppr}",
            f"Пропущено закрашенных: {len(colored_strings)}",
            f"Переносов/резервных назначений: {len(moved_strings or [])}",
        ]
        if printer_name:
            lines.append(f"Принтер: {printer_name}")
        scan = scan_printers_status(query_excel=False)
        pending = sum(r["jobs"] for r in scan["rows"])
        lines.append(f"Печать пойдёт на: {scan.get('target') or '—'}")
        if scan["excel_active"] and scan["default"] != scan["target"]:
            lines.append(
                f"Excel: {scan['excel_active']} (не совпадает с Windows default)"
            )
        if pending:
            lines.append(
                f"В очередях всего {pending} заданий — "
                "сначала «Очистить очередь печати»."
            )
        layout.addWidget(QLabel("\n".join(lines)))
        preview_parts = (colored_strings or [])[:4]
        if preview_parts:
            te = QTextEdit()
            te.setReadOnly(True)
            te.setMaximumHeight(80)
            te.setText("\n".join(preview_parts))
            layout.addWidget(te)
        hl = QHBoxLayout()
        btn_skip = QPushButton("Не печатать")
        btn_skip.clicked.connect(self.reject)
        btn_print = QPushButton(f"Печатать {total_files} файлов")
        btn_print.setStyleSheet("background:#D32F2F;color:white;font-weight:bold;")
        btn_print.clicked.connect(self._on_print)
        hl.addWidget(btn_skip)
        hl.addWidget(btn_print)
        layout.addLayout(hl)

    def _on_print(self):
        self._confirmed_print = True
        self.accept()

    def confirmed_print(self):
        return self._confirmed_print


class BulkGenDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Массовая генерация ССЗ")
        self.resize(480, 340)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Укажите границы периода:"))
        hl_dates = QHBoxLayout()
        vl_start = QVBoxLayout()
        vl_start.addWidget(QLabel("С КАКОГО ЧИСЛА:"))
        self.dt_start = QDateEdit(QDate.currentDate())
        self.dt_start.setCalendarPopup(True)
        self.dt_start.setDisplayFormat("dd.MM.yyyy")
        vl_start.addWidget(self.dt_start)
        hl_dates.addLayout(vl_start)
        vl_end = QVBoxLayout()
        vl_end.addWidget(QLabel("ПО КАКОЕ ЧИСЛО:"))
        self.dt_end = QDateEdit(QDate.currentDate().addDays(7))
        self.dt_end.setCalendarPopup(True)
        self.dt_end.setDisplayFormat("dd.MM.yyyy")
        vl_end.addWidget(self.dt_end)
        hl_dates.addLayout(vl_end)
        layout.addLayout(hl_dates)
        self.lbl_period = QLabel("")
        self.lbl_period.setStyleSheet("font-weight:bold;color:#0078D7;font-size:13px;")
        self.lbl_period.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_period)
        self.dt_start.dateChanged.connect(self._sync)
        self.dt_end.dateChanged.connect(self._sync)
        self._sync()
        self.cb_redistribute = QCheckBox("Не более 2 ППР одному исполнителю в день")
        self.cb_redistribute.setChecked(True)
        self.cb_redistribute.setEnabled(False)
        self.cb_redistribute.setToolTip("Обязательное правило безопасности")
        layout.addWidget(self.cb_redistribute)
        self.cb_print = QCheckBox("Отправлять сформированные файлы на принтер")
        self.cb_print.setStyleSheet("font-weight:bold;color:#D32F2F;")
        layout.addWidget(self.cb_print, alignment=Qt.AlignmentFlag.AlignCenter)
        hl_btns = QHBoxLayout()
        btn_start = QPushButton("Начать массовую генерацию")
        btn_start.setObjectName("btn_success")
        btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_start.clicked.connect(self._try_accept)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        hl_btns.addWidget(btn_start)
        hl_btns.addWidget(btn_cancel)
        layout.addLayout(hl_btns)

    def _sync(self):
        s = self.dt_start.date()
        self.dt_end.setMinimumDate(s)
        if self.dt_end.date() < s:
            self.dt_end.setDate(s)
        e = self.dt_end.date()
        days = s.daysTo(e) + 1
        self.lbl_period.setText(
            f"Период: {s.toString('dd.MM.yyyy')} — {e.toString('dd.MM.yyyy')} ({days} дн.)"
        )

    def _try_accept(self):
        days = self.dt_start.date().daysTo(self.dt_end.date()) + 1
        max_days = CONFIG.get("max_bulk_days", 62)
        if days > max_days:
            QMessageBox.warning(
                self,
                "Слишком длинный период",
                f"Максимум {max_days} дней за один раз.",
            )
            return
        self.accept()


class EditableComboDelegate(QStyledItemDelegate):
    """Выпадающий список с подсказками из кэша (редактируемый)."""

    def __init__(self, items, parent=None, formatter=None):
        super().__init__(parent)
        self._items = list(items)
        self._formatter = formatter

    def update_items(self, items):
        self._items = list(items)

    def createEditor(self, parent, option, index):
        editor = QComboBox(parent)
        editor.setEditable(True)
        editor.addItems(self._items)
        return editor

    def setEditorData(self, editor, index):
        text = index.data() or ""
        if text and editor.findText(text) < 0:
            editor.addItem(text)
        editor.setCurrentText(text)

    def setModelData(self, editor, model, index):
        text = editor.currentText().strip()
        if self._formatter and text:
            text = self._formatter(text)
        model.setData(index, text)


class BulkExtraTasksDialog(QDialog):
    """Дополнительные задания (1–2) на каждый день периода перед массовой генерацией."""

    COL_DATE = 0
    COL_DUTY = 1
    COL_W1 = 2
    COL_P1 = 3
    COL_E1 = 4
    COL_W2 = 5
    COL_P2 = 6
    COL_E2 = 7

    def __init__(self, dates, parent=None, cached_tasks=None, start_date=None, end_date=None, ppr_counts=None, all_colored=None):
        super().__init__(parent)
        self._dates = sorted(dates)
        self._start_date = start_date or (self._dates[0].date() if self._dates else date.today())
        self._end_date = end_date or (self._dates[-1].date() if self._dates else self._start_date)
        self.ppr_counts = ppr_counts or {}
        self.setWindowTitle("Дополнительные задания по дням")
        self.resize(1350, min(650, 160 + len(self._dates) * 28))
        root = QVBoxLayout(self)
        self.lbl_hint = QLabel(
            "<b>Укажите до двух дополнительных заданий на день (необязательно)</b><br>"
            "• В таблице указано количество заданий по графику (ППР).<br>"
            "• Два обхода КИП из шаблона добавляются автоматически.<br>"
            "• В таблице и в шаблоне «на все дни» — выпадающие подсказки из кэша заданий.<br>"
            "• Черновик сохраняется автоматически в «Кэш_массовых_доп_заданий.json»."
        )
        self.lbl_hint.setStyleSheet("font-size: 11pt; color: #1A1A2E; margin-bottom: 6px;")
        root.addWidget(self.lbl_hint)
        self.lbl_autosave = QLabel("")
        self.lbl_autosave.setStyleSheet("color:#2E7D32;font-size:11px;")
        root.addWidget(self.lbl_autosave)
        
        if all_colored:
            lbl_colored = QLabel(f"⚠️ <b>Внимание:</b> Пропущено закрашенных (отменённых) заданий в графиках: {len(all_colored)}<br>Они не будут включены в ССЗ.")
            lbl_colored.setStyleSheet("color: #D32F2F; font-size: 11pt; margin-bottom: 6px; padding: 4px; background: #FFEBEE; border-radius: 4px;")
            root.addWidget(lbl_colored)

        fill_gb = QGroupBox(" Заполнить все дни одним шаблоном ")
        fill_l = QVBoxLayout(fill_gb)
        row1 = QHBoxLayout()
        self.fill_w1 = QComboBox()
        self.fill_w1.setEditable(True)
        self.fill_w1.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.fill_w1.setMinimumContentsLength(10)
        self.fill_p1 = QComboBox()
        self.fill_p1.setEditable(True)
        self.fill_p1.setFixedWidth(160)
        self.fill_e1 = QComboBox()
        self.fill_e1.addItems(["Сменный", "Наладчик КИПиА Дмитриев И.С.", "Наладчик КИПиА Войтов А.М."])
        self.fill_e1.setFixedWidth(130)
        row1.addWidget(QLabel("Задание 1:"))
        row1.addWidget(self.fill_w1, stretch=1)
        row1.addWidget(self.fill_p1)
        row1.addWidget(self.fill_e1)
        fill_l.addLayout(row1)
        row2 = QHBoxLayout()
        self.fill_w2 = QComboBox()
        self.fill_w2.setEditable(True)
        self.fill_w2.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.fill_w2.setMinimumContentsLength(10)
        self.fill_p2 = QComboBox()
        self.fill_p2.setEditable(True)
        self.fill_p2.setFixedWidth(160)
        self.fill_e2 = QComboBox()
        self.fill_e2.addItems(["Сменный", "Наладчик КИПиА Дмитриев И.С.", "Наладчик КИПиА Войтов А.М."])
        self.fill_e2.setFixedWidth(130)
        row2.addWidget(QLabel("Задание 2:"))
        row2.addWidget(self.fill_w2, stretch=1)
        row2.addWidget(self.fill_p2)
        row2.addWidget(self.fill_e2)
        fill_l.addLayout(row2)
        btn_fill_all = QPushButton("Подставить во все дни периода")
        btn_fill_all.clicked.connect(self._fill_all_days)
        fill_l.addWidget(btn_fill_all)
        btn_save_draft = QPushButton("Сохранить черновик сейчас")
        btn_save_draft.clicked.connect(self._autosave_draft)
        fill_l.addWidget(btn_save_draft)
        root.addWidget(fill_gb)

        self._works, self._places = manual_cache_combo_lists(cached_tasks or [])
        self._populate_fill_combos()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_l = QVBoxLayout(inner)
        self.table = QTableWidget(len(self._dates), 8)
        self.table.setHorizontalHeaderLabels(
            ["Дата", "Сменный", "Задание 1", "Место 1", "Исп. 1", "Задание 2", "Место 2", "Исп. 2"]
        )
        self.table.setWordWrap(True)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(self.COL_DATE, 120)
        self.table.setColumnWidth(self.COL_DUTY, 110)
        self.table.horizontalHeader().setSectionResizeMode(
            self.COL_W1, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            self.COL_W2, QHeaderView.ResizeMode.Stretch
        )
        self.table.setColumnWidth(self.COL_P1, 160)
        self.table.setColumnWidth(self.COL_P2, 160)
        self.table.setColumnWidth(self.COL_E1, 130)
        self.table.setColumnWidth(self.COL_E2, 130)
        read_only = Qt.ItemFlag.ItemIsEditable
        for row, d in enumerate(self._dates):
            d_str = d.strftime("%d.%m.%Y")
            cnt = self.ppr_counts.get(d_str, 0)
            date_label = f"{d_str} (ППР: {cnt})" if cnt > 0 else d_str
            date_item = QTableWidgetItem(date_label)
            if cnt > 0:
                date_item.setBackground(QColor("#FFF3E0"))
                date_item.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            date_item.setFlags(date_item.flags() & ~read_only)
            self.table.setItem(row, self.COL_DATE, date_item)
            duty_item = QTableWidgetItem(get_duty_surname(d))
            if cnt > 0:
                duty_item.setBackground(QColor("#FFF3E0"))
            duty_item.setFlags(duty_item.flags() & ~read_only)
            self.table.setItem(row, self.COL_DUTY, duty_item)
            for col in (self.COL_W1, self.COL_P1, self.COL_E1, self.COL_W2, self.COL_P2, self.COL_E2):
                self.table.setItem(row, col, QTableWidgetItem(""))
        
        self._work_delegate = EditableComboDelegate(self._works, self.table, formatter=auto_correct_task)
        self._place_delegate = EditableComboDelegate(self._places, self.table, formatter=auto_correct_place)
        self._exec_delegate = EditableComboDelegate(["", "Сменный", "Наладчик КИПиА Дмитриев И.С.", "Наладчик КИПиА Войтов А.М."], self.table)
        
        self.table.setItemDelegateForColumn(self.COL_W1, self._work_delegate)
        self.table.setItemDelegateForColumn(self.COL_W2, self._work_delegate)
        self.table.setItemDelegateForColumn(self.COL_P1, self._place_delegate)
        self.table.setItemDelegateForColumn(self.COL_P2, self._place_delegate)
        self.table.setItemDelegateForColumn(self.COL_E1, self._exec_delegate)
        self.table.setItemDelegateForColumn(self.COL_E2, self._exec_delegate)
        inner_l.addWidget(self.table)
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

        hl_kip = QHBoxLayout()
        self.btn_kip_chart = QPushButton("Печать графика замены д-мм за период")
        self.btn_kip_chart.setStyleSheet("color:#1565C0;font-weight:bold;")
        self.btn_kip_chart.clicked.connect(self._print_kip_chart)
        hl_kip.addWidget(self.btn_kip_chart)
        hl_kip.addStretch()
        root.addLayout(hl_kip)

        hl = QHBoxLayout()
        btn_ok = QPushButton("Продолжить массовую генерацию")
        btn_ok.setObjectName("btn_success")
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.clicked.connect(self.accept)
        btn_skip = QPushButton("Без доп. заданий")
        btn_skip.clicked.connect(self.accept)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        hl.addWidget(btn_ok)
        hl.addWidget(btn_skip)
        hl.addWidget(btn_cancel)
        root.addLayout(hl)

        draft = load_bulk_extra_draft(self._start_date, self._end_date)
        if draft:
            self._apply_extra_to_table(draft)
            self.lbl_autosave.setText(
                f"Восстановлен черновик ({len(draft)} дн. с заданиями)."
            )
        self._autosave_timer = QTimer(self)
        interval = max(5, int(CONFIG.get("bulk_extra_autosave_s", 20))) * 1000
        self._autosave_timer.setInterval(interval)
        self._autosave_timer.timeout.connect(self._autosave_draft)
        self._autosave_timer.start()

    def closeEvent(self, event):
        self._autosave_draft(silent=True)
        super().closeEvent(event)

    def reject(self):
        self._autosave_draft(silent=True)
        super().reject()

    def _row_date_str(self, row):
        item = self.table.item(row, self.COL_DATE)
        return (item.text() if item else "").strip()

    def _apply_extra_to_table(self, extra_by_date):
        for row in range(self.table.rowCount()):
            d_str = self._dates[row].strftime("%d.%m.%Y")
            tasks = extra_by_date.get(d_str) or []
            slots = (
                (self.COL_W1, self.COL_P1, self.COL_E1),
                (self.COL_W2, self.COL_P2, self.COL_E2),
            )
            for si, (w_col, p_col, e_col) in enumerate(slots):
                work, place, exec_name = "", "", ""
                if si < len(tasks):
                    work = tasks[si].get("work", "")
                    place = tasks[si].get("place", "")
                    exec_name = tasks[si].get("executor", "")
                if work and not exec_name:
                    exec_name = "Сменный"
                self.table.setItem(row, w_col, QTableWidgetItem(work))
                self.table.setItem(row, p_col, QTableWidgetItem(place))
                self.table.setItem(row, e_col, QTableWidgetItem(exec_name))

    def _autosave_draft(self, silent=False):
        data = self.get_extra_by_date()
        ok = save_bulk_extra_draft(self._start_date, self._end_date, data)
        if ok and not silent:
            n = sum(len(v) for v in data.values())
            self.lbl_autosave.setText(
                f"Черновик сохранён ({datetime.now().strftime('%H:%M:%S')}), "
                f"дней с заданиями: {len(data)}, записей: {n}"
            )

    def _populate_fill_combos(self):
        for combo, items in (
            (self.fill_w1, self._works),
            (self.fill_w2, self._works),
            (self.fill_p1, self._places),
            (self.fill_p2, self._places),
        ):
            combo.clear()
            combo.addItems(items)

    def _print_kip_chart(self):
        if not self._dates:
            return
        start = min(self._dates).date()
        end = max(self._dates).date()
        parent = self.parent()
        if parent is not None and hasattr(parent, "run_kip_dmm_schedule"):
            self.hide()
            try:
                parent.run_kip_dmm_schedule(start, end, ask_dialog=False, default_print=True)
            finally:
                self.show()
        else:
            QMessageBox.information(
                self,
                "График д-мм",
                f"Период: {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}",
            )

    def _fill_all_days(self):
        work1 = auto_correct_task(self.fill_w1.currentText().strip()) if self.fill_w1.currentText().strip() else ""
        place1 = auto_correct_place(self.fill_p1.currentText().strip()) if self.fill_p1.currentText().strip() else ""
        exec1 = self.fill_e1.currentText().strip()
        work2 = auto_correct_task(self.fill_w2.currentText().strip()) if self.fill_w2.currentText().strip() else ""
        place2 = auto_correct_place(self.fill_p2.currentText().strip()) if self.fill_p2.currentText().strip() else ""
        exec2 = self.fill_e2.currentText().strip()
        
        self.fill_w1.setCurrentText(work1)
        self.fill_p1.setCurrentText(place1)
        self.fill_e1.setCurrentText(exec1)
        self.fill_w2.setCurrentText(work2)
        self.fill_p2.setCurrentText(place2)
        self.fill_e2.setCurrentText(exec2)
        
        slots = [
            (work1, place1, exec1),
            (work2, place2, exec2),
        ]
        for row in range(self.table.rowCount()):
            for si, (work, place, exec_name) in enumerate(slots):
                w_col = self.COL_W1 if si == 0 else self.COL_W2
                p_col = self.COL_P1 if si == 0 else self.COL_P2
                e_col = self.COL_E1 if si == 0 else self.COL_E2
                self.table.setItem(row, w_col, QTableWidgetItem(work))
                self.table.setItem(row, p_col, QTableWidgetItem(place))
                self.table.setItem(row, e_col, QTableWidgetItem(exec_name))

    def get_extra_by_date(self):
        result = {}
        for row in range(self.table.rowCount()):
            d_str = self._dates[row].strftime("%d.%m.%Y")
            day_tasks = []
            for w_col, p_col, e_col in ((self.COL_W1, self.COL_P1, self.COL_E1), (self.COL_W2, self.COL_P2, self.COL_E2)):
                w_item = self.table.item(row, w_col)
                p_item = self.table.item(row, p_col)
                e_item = self.table.item(row, e_col)
                work = (w_item.text() if w_item else "").strip()
                place = (p_item.text() if p_item else "").strip()
                exec_name = (e_item.text() if e_item else "").strip()
                if exec_name == "Сменный":
                    exec_name = ""
                if not work and not place:
                    continue
                if work:
                    work = auto_correct_task(work)
                if place:
                    place = auto_correct_place(place)
                else:
                    place = auto_correct_place("")
                if work:
                    day_tasks.append({"work": work, "place": place, "executor": exec_name})
            if day_tasks:
                result[d_str] = day_tasks[:2]
        return result


class ExecutorOverrideDialog(QDialog):
    """Табель сменного и дневного персонала с отсутствиями и замещениями."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Табель сотрудников")
        self.resize(1450, 900)
        self.setMinimumSize(1050, 680)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setStyleSheet("""
            QGroupBox { font-weight: 700; border: 1px solid #CBD5E1; border-radius: 8px;
                        margin-top: 12px; padding-top: 10px; background: #FFFFFF; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #1E293B; }
            QTableWidget { border: 1px solid #CBD5E1; gridline-color: #E2E8F0;
                           selection-background-color: #DBEAFE; selection-color: #0F172A; }
            QHeaderView::section { background: #F1F5F9; color: #334155; font-weight: 700;
                                   padding: 7px; border: none; border-right: 1px solid #CBD5E1;
                                   border-bottom: 1px solid #CBD5E1; }
            QPushButton { min-height: 28px; padding: 3px 12px; }
            QComboBox, QDateEdit { min-height: 26px; padding-left: 5px; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_block = QVBoxLayout()
        title = QLabel("Табель сотрудников и замещений")
        title.setStyleSheet("font-size:20px;font-weight:700;color:#0F172A;")
        subtitle = QLabel("Выделите период в строке сотрудника и укажите отпуск, больничный или другое изменение.")
        subtitle.setStyleSheet("color:#64748B;")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        title_row.addLayout(title_block)
        title_row.addStretch()
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet(
            "background:#F8FAFC;border:1px solid #CBD5E1;border-radius:7px;padding:8px 12px;color:#334155;"
        )
        title_row.addWidget(self.summary_label)
        layout.addLayout(title_row)

        self.month_page = QWidget()
        self.editor_page = QWidget()
        self._setup_month_page()
        editor_layout = QVBoxLayout(self.editor_page)
        editor_layout.setContentsMargins(8, 8, 8, 8)
        splitter = QSplitter(Qt.Orientation.Vertical)

        staff_group = QGroupBox("1. Состав и режим работы")
        staff_layout = QVBoxLayout(staff_group)
        staff_toolbar = QHBoxLayout()
        btn_staff_add = QPushButton("＋ Добавить сотрудника")
        btn_staff_add.setObjectName("btn_primary")
        btn_staff_absence = QPushButton("Отметить отсутствие выбранного")
        btn_staff_del = QPushButton("Убрать выбранного из списка")
        btn_staff_add.clicked.connect(self._add_staff_row)
        btn_staff_absence.clicked.connect(self._add_absence_for_selected_staff)
        btn_staff_del.clicked.connect(self._delete_staff_row)
        staff_toolbar.addWidget(btn_staff_add)
        staff_toolbar.addWidget(btn_staff_absence)
        staff_toolbar.addStretch()
        staff_toolbar.addWidget(btn_staff_del)
        staff_layout.addLayout(staff_toolbar)

        self.staff_table = QTableWidget(0, 4)
        self.staff_table.setHorizontalHeaderLabels(["Работает", "ФИО сотрудника", "График", "Должность"])
        self._configure_table(self.staff_table)
        staff_header = self.staff_table.horizontalHeader()
        staff_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        staff_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        staff_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        staff_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        staff_layout.addWidget(self.staff_table)
        staff_help = QLabel(
            "Сменный 1 и Сменный 2 чередуются по циклу 2/2. Дневной работает по будням. "
            "Снимите флажок «Работает», если сотрудник больше не участвует в планировании."
        )
        staff_help.setWordWrap(True)
        staff_help.setStyleSheet("color:#64748B;font-size:11px;")
        staff_layout.addWidget(staff_help)
        splitter.addWidget(staff_group)

        absence_group = QGroupBox("2. Отпуска, больничные и другие отсутствия")
        absence_layout = QVBoxLayout(absence_group)
        absence_toolbar = QHBoxLayout()
        self.btn_add = QPushButton("＋ Добавить отсутствие")
        self.btn_add.setObjectName("btn_primary")
        self.btn_del = QPushButton("Удалить выбранную строку")
        absence_toolbar.addWidget(self.btn_add)
        absence_toolbar.addStretch()
        absence_toolbar.addWidget(self.btn_del)
        absence_layout.addLayout(absence_toolbar)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Кто отсутствует", "Причина", "Дата начала", "Дата окончания", "Замещает", "Примечание", "ID"]
        )
        self._configure_table(self.table)
        self.table.setColumnHidden(6, True)
        header = self.table.horizontalHeader()
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for column in (0, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        absence_layout.addWidget(self.table)
        absence_help = QLabel(
            "Для сменного сотрудника замена обязательна. Без замены программа остановит создание ССЗ на эту дату, "
            "чтобы задание не было выдано отсутствующему человеку."
        )
        absence_help.setWordWrap(True)
        absence_help.setStyleSheet(
            "background:#FFF7ED;border:1px solid #FDBA74;color:#9A3412;padding:7px;border-radius:5px;"
        )
        absence_layout.addWidget(absence_help)
        splitter.addWidget(absence_group)
        splitter.setSizes([280, 360])
        editor_layout.addWidget(splitter)
        layout.addWidget(self.month_page, 1)

        self.btn_save = QPushButton("Сохранить изменения табеля")
        self.btn_save.setObjectName("btn_success")
        self.btn_cancel = QPushButton("Отмена")
        save_layout = QHBoxLayout()
        save_note = QLabel("Состав сотрудников изменяется отдельно в настройках системы")
        save_note.setStyleSheet("color:#64748B;")
        save_layout.addWidget(save_note)
        save_layout.addStretch()
        save_layout.addWidget(self.btn_save)
        save_layout.addWidget(self.btn_cancel)
        layout.addLayout(save_layout)

        self.btn_add.clicked.connect(self._add_row)
        self.btn_del.clicked.connect(self._delete_absence_row)
        self.btn_save.clicked.connect(self._save)
        self.btn_cancel.clicked.connect(self.reject)
        self.staff_table.itemChanged.connect(self._on_staff_item_changed)

        self._load_data()

    def _setup_month_page(self):
        month_layout = QVBoxLayout(self.month_page)
        month_layout.setContentsMargins(8, 10, 8, 8)
        month_layout.setSpacing(8)

        toolbar = QHBoxLayout()
        btn_prev = QPushButton("←")
        btn_prev.setFixedWidth(42)
        btn_prev.setToolTip("Предыдущий месяц")
        btn_prev.clicked.connect(lambda: self._shift_month(-1))
        self.month_combo = QComboBox()
        self.month_combo.addItems(
            [
                "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
            ]
        )
        self.month_combo.setCurrentIndex(date.today().month - 1)
        self.month_year = QSpinBox()
        self.month_year.setRange(2020, 2100)
        self.month_year.setValue(date.today().year)
        btn_next = QPushButton("→")
        btn_next.setFixedWidth(42)
        btn_next.setToolTip("Следующий месяц")
        btn_next.clicked.connect(lambda: self._shift_month(1))
        btn_today = QPushButton("Текущий месяц")
        btn_today.clicked.connect(self._go_current_month)
        self.cell_size_combo = QComboBox()
        self.cell_size_combo.addItem("Компактные ячейки", (29, 44, 245, 9))
        self.cell_size_combo.addItem("Крупные ячейки", (38, 60, 315, 10))
        self.cell_size_combo.addItem("Очень крупные", (48, 74, 380, 11))
        self.cell_size_combo.setCurrentIndex(1)
        self.cell_size_combo.setToolTip("Изменяет ширину дней, высоту строк и размер текста")
        toolbar.addWidget(btn_prev)
        toolbar.addWidget(self.month_combo)
        toolbar.addWidget(self.month_year)
        toolbar.addWidget(btn_next)
        toolbar.addWidget(btn_today)
        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("Масштаб:"))
        toolbar.addWidget(self.cell_size_combo)
        toolbar.addStretch()
        month_layout.addLayout(toolbar)

        legend = QFrame()
        legend.setStyleSheet("QFrame { background:#F8FAFC;border:1px solid #CBD5E1;border-radius:6px; }")
        legend_layout = QGridLayout(legend)
        legend_layout.setContentsMargins(9, 6, 9, 6)
        legend_layout.addWidget(QLabel("Обозначения:"), 0, 0, 2, 1)
        legend_items = (
            ("С", "смена", "#93C5FD"),
            ("Д", "дневная работа", "#86EFAC"),
            ("В", "выходной", "#CBD5E1"),
            ("О", "отпуск", "#FACC15"),
            ("Б", "больничный", "#F87171"),
            ("СЧ", "свой счёт", "#FB923C"),
            ("К", "командировка / обучение", "#C4B5FD"),
            ("ОГ", "отгул", "#FED7AA"),
            ("Н", "другое", "#FBCFE8"),
        )
        for index, (code, text, color) in enumerate(legend_items):
            label = QLabel(f" <b>{code}</b> — {text} ")
            label.setStyleSheet(f"background:{color};border-radius:4px;padding:3px 5px;")
            legend_layout.addWidget(label, index // 5, index % 5 + 1)
        legend_layout.setColumnStretch(6, 1)
        month_layout.addWidget(legend)

        action_frame = QFrame()
        action_frame.setStyleSheet(
            "QFrame { background:#FFFFFF;border:1px solid #94A3B8;border-radius:7px; }"
        )
        action_layout = QVBoxLayout(action_frame)
        action_layout.setContentsMargins(10, 8, 10, 8)
        action_layout.setSpacing(6)
        self.selection_label = QLabel("Выделите мышью дни одного сотрудника")
        self.selection_label.setStyleSheet("font-weight:700;color:#1E293B;")
        action_layout.addWidget(self.selection_label)
        action_top = QHBoxLayout()
        self.absence_kind_combo = QComboBox()
        from staff_schedule import ABSENCE_TYPES
        self.absence_kind_combo.addItems(ABSENCE_TYPES)
        self.replacement_combo = QComboBox()
        self.replacement_combo.setEditable(True)
        self.replacement_combo.setMinimumWidth(240)
        self.btn_apply_range = QPushButton("Применить к выделенным дням")
        self.btn_apply_range.setObjectName("btn_primary")
        self.btn_clear_range = QPushButton("Вернуть рабочий график")
        self.btn_apply_range.setEnabled(False)
        self.btn_clear_range.setEnabled(False)
        action_top.addWidget(QLabel("Что изменилось:"))
        action_top.addWidget(self.absence_kind_combo)
        action_top.addWidget(QLabel("Замещает:"))
        action_top.addWidget(self.replacement_combo)
        action_top.addWidget(self.btn_apply_range)
        action_top.addWidget(self.btn_clear_range)
        action_top.addStretch()
        action_layout.addLayout(action_top)
        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("Разовый обмен / ручной график:"))
        self.manual_status_combo = QComboBox()
        self.manual_status_combo.addItem("Рабочая смена", "work")
        self.manual_status_combo.addItem("Выходной", "off")
        self.manual_replaces_combo = QComboBox()
        self.manual_replaces_combo.addItem("По плановому графику", "__planned__")
        self.manual_replaces_combo.setMinimumWidth(230)
        self.manual_reason = QLineEdit("Обмен сменами / личная договорённость")
        self.manual_reason.setPlaceholderText("Причина изменения")
        self.btn_apply_manual = QPushButton("Записать ручную смену")
        self.btn_apply_manual.setEnabled(False)
        manual_row.addWidget(self.manual_status_combo)
        manual_row.addWidget(QLabel("Вместо кого:"))
        manual_row.addWidget(self.manual_replaces_combo)
        manual_row.addWidget(self.manual_reason, 1)
        manual_row.addWidget(self.btn_apply_manual)
        action_layout.addLayout(manual_row)
        self.smart_hint = QLabel(
            "Подсказка появится после выделения диапазона. Для выбора недели зажмите левую кнопку мыши и протяните по строке."
        )
        self.smart_hint.setWordWrap(True)
        self.smart_hint.setStyleSheet("color:#64748B;")
        action_layout.addWidget(self.smart_hint)
        month_layout.addWidget(action_frame)

        self.month_table = QTableWidget()
        self._configure_table(self.month_table)
        self.month_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.month_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.month_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.month_table.setWordWrap(True)
        self.month_table.horizontalHeader().setMinimumSectionSize(28)
        self.month_table.cellDoubleClicked.connect(self._month_cell_double_clicked)
        self.month_table.itemSelectionChanged.connect(self._update_selection_panel)
        month_layout.addWidget(self.month_table, 1)
        month_hint = QLabel(
            "Выделяйте дни протягиванием мыши по одной строке. Ctrl позволяет добавить отдельные дни. "
            "Наведите курсор на ячейку для подробностей и сведений о замене."
        )
        month_hint.setStyleSheet("color:#64748B;")
        month_layout.addWidget(month_hint)

        self.month_combo.currentIndexChanged.connect(self._refresh_month_table)
        self.month_year.valueChanged.connect(self._refresh_month_table)
        self.cell_size_combo.currentIndexChanged.connect(self._refresh_month_table)
        self.absence_kind_combo.currentIndexChanged.connect(self._update_selection_panel)
        self.btn_apply_range.clicked.connect(self._apply_selected_absence)
        self.btn_clear_range.clicked.connect(self._clear_selected_absence)
        self.manual_status_combo.currentIndexChanged.connect(
            lambda: self.manual_replaces_combo.setEnabled(self.manual_status_combo.currentData() == "work")
        )
        self.btn_apply_manual.clicked.connect(self._apply_manual_schedule)

    def _shift_month(self, delta):
        month = self.month_combo.currentIndex() + 1 + int(delta)
        year = self.month_year.value()
        if month < 1:
            month, year = 12, year - 1
        elif month > 12:
            month, year = 1, year + 1
        self.month_year.blockSignals(True)
        self.month_combo.blockSignals(True)
        self.month_year.setValue(year)
        self.month_combo.setCurrentIndex(month - 1)
        self.month_combo.blockSignals(False)
        self.month_year.blockSignals(False)
        self._refresh_month_table()

    def _go_current_month(self):
        today = date.today()
        self.month_year.setValue(today.year)
        self.month_combo.setCurrentIndex(today.month - 1)
        self._refresh_month_table()

    @staticmethod
    def _absence_code(kind):
        return {
            "Отпуск": ("О", "#FACC15"),
            "Больничный": ("Б", "#F87171"),
            "За свой счёт": ("СЧ", "#FB923C"),
            "Командировка": ("К", "#C4B5FD"),
            "Обучение": ("К", "#C4B5FD"),
            "Отгул": ("ОГ", "#FED7AA"),
            "Другое": ("Н", "#FBCFE8"),
        }.get(kind, ("Н", "#FBCFE8"))

    def _selected_month_range(self, allow_gaps=False):
        cells = [item for item in self.month_table.selectedItems() if item.column() > 0]
        if not cells:
            return None, "Выделите один или несколько дней в строке сотрудника."
        rows = {item.row() for item in cells}
        if len(rows) != 1:
            return None, "За один раз можно изменять дни только одного сотрудника."
        columns = sorted({item.column() for item in cells})
        if not allow_gaps and columns != list(range(columns[0], columns[-1] + 1)):
            return None, "Дни должны идти подряд. Для разных периодов примените изменения отдельно."
        row = next(iter(rows))
        staff = self._staff_data()
        if row >= len(staff):
            return None, "Не удалось определить сотрудника для выделения."
        start = date.fromisoformat(self.month_table.item(row, columns[0]).data(Qt.ItemDataRole.UserRole + 1))
        end = date.fromisoformat(self.month_table.item(row, columns[-1]).data(Qt.ItemDataRole.UserRole + 1))
        member = staff[row]
        selected_dates = [
            date.fromisoformat(self.month_table.item(row, column).data(Qt.ItemDataRole.UserRole + 1))
            for column in columns
        ]
        epoch = CONFIG.get("duty_epoch", start)
        needs_replacement = False
        if member["work_mode"].startswith("shift_"):
            for current in selected_dates:
                planned = "shift_a" if ((current - epoch).days // 2) % 2 == 0 else "shift_b"
                if planned == member["work_mode"]:
                    needs_replacement = True
                    break
        return {
            "member": member,
            "start": start,
            "end": end,
            "dates": selected_dates,
            "contiguous": columns == list(range(columns[0], columns[-1] + 1)),
            "needs_replacement": needs_replacement,
        }, ""

    def _staff_free_for_period(self, name, start, end):
        display_name = str(name or "").strip()
        for item in self.get_data():
            if item["staff_name"] != display_name:
                continue
            if item["start"] <= end.isoformat() and item["end"] >= start.isoformat():
                return False
        for item in getattr(self, "day_override_rows", []):
            if not start.isoformat() <= item.get("date", "") <= end.isoformat():
                continue
            if item.get("staff_name") == display_name:
                return False
            if item.get("replaces_name") == display_name:
                return False
        return True

    def _update_selection_panel(self, *_args):
        if not hasattr(self, "selection_label"):
            return
        selection, error = self._selected_month_range(allow_gaps=True)
        if not selection:
            self.selection_label.setText(error or "Выделите дни одного сотрудника")
            self.smart_hint.setText(
                "Выделяйте непрерывный период протягиванием мыши по строке одного сотрудника."
            )
            self.smart_hint.setStyleSheet("color:#64748B;")
            self.btn_apply_range.setEnabled(False)
            self.btn_clear_range.setEnabled(False)
            self.btn_apply_manual.setEnabled(False)
            return

        member = selection["member"]
        start, end = selection["start"], selection["end"]
        days = len(selection["dates"])
        period_text = (
            f"{start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}"
            if selection["contiguous"]
            else ", ".join(value.strftime("%d.%m") for value in selection["dates"])
        )
        self.selection_label.setText(f"{member['name']} · {period_text} · {days} дн.")
        previous = self.replacement_combo.currentText().strip()
        self.replacement_combo.blockSignals(True)
        self.replacement_combo.clear()
        self.replacement_combo.addItem("")
        candidates = [
            row for row in self._staff_data()
            if row["active"] and row["name"] != member["name"]
            and self._staff_free_for_period(row["name"], start, end)
        ]
        candidates.sort(key=lambda row: (row["work_mode"] != "day", row["name"]))
        self.replacement_combo.addItems([row["name"] for row in candidates])
        if previous and self.replacement_combo.findText(previous) >= 0:
            self.replacement_combo.setCurrentText(previous)
        elif selection["needs_replacement"] and candidates:
            self.replacement_combo.setCurrentText(candidates[0]["name"])
        self.replacement_combo.blockSignals(False)

        previous_manual = self.manual_replaces_combo.currentData()
        self.manual_replaces_combo.blockSignals(True)
        self.manual_replaces_combo.clear()
        self.manual_replaces_combo.addItem("По плановому графику", "__planned__")
        for row in self._staff_data():
            if row["active"] and row["name"] != member["name"]:
                self.manual_replaces_combo.addItem(row["name"], row["name"])
        previous_index = self.manual_replaces_combo.findData(previous_manual)
        self.manual_replaces_combo.setCurrentIndex(max(previous_index, 0))
        self.manual_replaces_combo.blockSignals(False)

        if selection["needs_replacement"]:
            if candidates:
                self.smart_hint.setText(
                    f"Сменному нужна замена. Предложен свободный сотрудник: {candidates[0]['name']}. "
                    "Проверьте выбор перед применением."
                )
                self.smart_hint.setStyleSheet("color:#166534;font-weight:600;")
            else:
                self.smart_hint.setText(
                    "На выбранный период свободная замена не найдена. Укажите фамилию вручную — без замены табель не сохранится."
                )
                self.smart_hint.setStyleSheet("color:#B91C1C;font-weight:600;")
        else:
            self.smart_hint.setText(
                "В выбранном периоде нет рабочих смен этого сотрудника, поэтому замена необязательна."
                if member["work_mode"].startswith("shift_")
                else "Для дневного сотрудника замена необязательна. При необходимости выберите её вручную."
            )
            self.smart_hint.setStyleSheet("color:#475569;")
        self.btn_apply_range.setEnabled(selection["contiguous"])
        self.btn_clear_range.setEnabled(selection["contiguous"])
        self.btn_apply_manual.setEnabled(True)
        if not selection["contiguous"]:
            self.smart_hint.setText(
                "Выбраны отдельные дни. Для них можно записать ручные рабочие смены или выходные. "
                "Отпуск и другое отсутствие оформляются только непрерывным периодом."
            )
            self.smart_hint.setStyleSheet("color:#1D4ED8;font-weight:600;")

    def _rewrite_absence_range(self, selection, add_new):
        member = selection["member"]
        start, end = selection["start"], selection["end"]
        rewritten = []
        for item in self.get_data():
            item_start = date.fromisoformat(item["start"])
            item_end = date.fromisoformat(item["end"])
            if item["staff_name"] != member["name"] or item_end < start or item_start > end:
                rewritten.append(dict(item))
                continue
            if item_start < start:
                left = dict(item)
                left["end"] = (start - timedelta(days=1)).isoformat()
                rewritten.append(left)
            if item_end > end:
                right = dict(item)
                right["start"] = (end + timedelta(days=1)).isoformat()
                rewritten.append(right)
        if add_new:
            rewritten.append(
                {
                    "staff_name": member["name"],
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "absence_type": self.absence_kind_combo.currentText().strip(),
                    "replacement_name": self.replacement_combo.currentText().strip(),
                    "note": "Изменено в месячном табеле",
                }
            )
        rewritten.sort(key=lambda item: (item["start"], item["staff_name"]))
        self.table.setRowCount(0)
        for item in rewritten:
            self._add_row(item)
        self._refresh_month_table()

    def _apply_selected_absence(self):
        selection, error = self._selected_month_range()
        if not selection:
            QMessageBox.information(self, "Табель", error)
            return
        if selection["needs_replacement"] and not self.replacement_combo.currentText().strip():
            QMessageBox.warning(
                self,
                "Нужна замена",
                "В период попадает рабочая смена сотрудника. Выберите заменяющего — иначе ССЗ на эту дату будет заблокировано.",
            )
            return
        self._rewrite_absence_range(selection, add_new=True)
        self.smart_hint.setText("Изменение внесено в табель. Нажмите «Сохранить табель», чтобы применить его в системе.")
        self.smart_hint.setStyleSheet("color:#166534;font-weight:600;")

    def _clear_selected_absence(self):
        selection, error = self._selected_month_range()
        if not selection:
            QMessageBox.information(self, "Табель", error)
            return
        self._rewrite_absence_range(selection, add_new=False)
        selected_dates = {value.isoformat() for value in selection["dates"]}
        self.day_override_rows = [
            row for row in self.day_override_rows
            if not (
                row.get("staff_name") == selection["member"]["name"]
                and row.get("date") in selected_dates
            )
        ]
        self._refresh_month_table()
        self.smart_hint.setText("Для выбранных дней восстановлен обычный рабочий график.")
        self.smart_hint.setStyleSheet("color:#166534;font-weight:600;")

    def _planned_shift_name(self, current):
        epoch = CONFIG.get("duty_epoch", current)
        planned_mode = "shift_a" if ((current - epoch).days // 2) % 2 == 0 else "shift_b"
        member = next(
            (row for row in self._staff_data() if row["active"] and row["work_mode"] == planned_mode),
            None,
        )
        if member:
            return member["name"]
        return CONFIG.get("executor_1" if planned_mode == "shift_a" else "executor_2", "")

    def _apply_manual_schedule(self):
        selection, error = self._selected_month_range(allow_gaps=True)
        if not selection:
            QMessageBox.information(self, "Табель", error)
            return
        member_name = selection["member"]["name"]
        status = self.manual_status_combo.currentData()
        chosen_replacement = self.manual_replaces_combo.currentData()
        selected_iso = {value.isoformat() for value in selection["dates"]}
        self.day_override_rows = [
            row for row in self.day_override_rows
            if not (row.get("staff_name") == member_name and row.get("date") in selected_iso)
        ]
        for current in selection["dates"]:
            replaces_name = ""
            if status == "work":
                replaces_name = (
                    self._planned_shift_name(current)
                    if chosen_replacement == "__planned__"
                    else str(chosen_replacement or "")
                )
                if replaces_name == member_name:
                    replaces_name = ""
            self.day_override_rows.append(
                {
                    "date": current.isoformat(),
                    "staff_name": member_name,
                    "status": status,
                    "replaces_name": replaces_name,
                    "reason": self.manual_reason.text().strip(),
                }
            )
        self.day_override_rows.sort(key=lambda row: (row["date"], row["staff_name"]))
        self._refresh_month_table()
        action = "рабочими сменами" if status == "work" else "выходными"
        self.smart_hint.setText(
            f"Выбранные дни отмечены {action}. Сохраните табель, чтобы изменения учитывались при создании ССЗ."
        )
        self.smart_hint.setStyleSheet("color:#166534;font-weight:600;")

    def _refresh_month_table(self, *_args):
        if not hasattr(self, "month_table") or not hasattr(self, "staff_table"):
            return
        year = self.month_year.value()
        month = self.month_combo.currentIndex() + 1
        days = calendar.monthrange(year, month)[1]
        day_width, row_height, name_width, font_size = (
            self.cell_size_combo.currentData() or (38, 60, 315, 10)
        )
        staff = self._staff_data()
        staff_by_name = {row["name"]: row for row in staff}
        absences = self.get_data()
        day_overrides = getattr(self, "day_override_rows", [])
        from staff_schedule import _display_name
        if staff and self.cell_size_combo.currentIndex() > 0:
            available_height = max(0, self.month_table.viewport().height() - 4)
            row_height = max(row_height, min(96, available_height // len(staff)))
        self.month_table.blockSignals(True)
        try:
            self.month_table.clear()
            self.month_table.setRowCount(len(staff))
            self.month_table.setColumnCount(days + 1)
            headers = ["Сотрудник / график"]
            weekdays = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
            for day_number in range(1, days + 1):
                current = date(year, month, day_number)
                headers.append(f"{day_number}\n{weekdays[current.weekday()]}")
            self.month_table.setHorizontalHeaderLabels(headers)
            self.month_table.horizontalHeader().setFixedHeight(max(48, row_height - 6))
            self.month_table.setColumnWidth(0, name_width)
            for column in range(1, days + 1):
                self.month_table.setColumnWidth(column, day_width)
                current = date(year, month, column)
                if current.weekday() >= 5:
                    header_item = self.month_table.horizontalHeaderItem(column)
                    header_item.setBackground(QColor("#FECACA"))
                    header_item.setForeground(QColor("#991B1B"))

            epoch = CONFIG.get("duty_epoch", date(year, month, 1))
            for row, member in enumerate(staff):
                name = member["name"]
                mode = member["work_mode"]
                mode_text = {"shift_a": "Сменный 1", "shift_b": "Сменный 2", "day": "Дневной"}.get(mode, mode)
                name_item = QTableWidgetItem(f"{name}\n{mode_text}")
                name_item.setToolTip(f"{name}\nГрафик: {mode_text}\nДолжность: {member.get('role', '')}")
                name_item.setFont(QFont("Segoe UI", font_size, QFont.Weight.DemiBold))
                if not member["active"]:
                    name_item.setForeground(QColor("#94A3B8"))
                self.month_table.setItem(row, 0, name_item)
                self.month_table.setRowHeight(row, row_height)

                for day_number in range(1, days + 1):
                    current = date(year, month, day_number)
                    iso = current.isoformat()
                    block = ((current - epoch).days // 2) % 2
                    planned_mode = "shift_a" if block == 0 else "shift_b"
                    absence = next(
                        (
                            item for item in absences
                            if item["start"] <= iso <= item["end"]
                            and (
                                item["staff_name"] == name
                                or (
                                    item["staff_name"] == "Любого сменного"
                                    and mode == planned_mode
                                )
                            )
                        ),
                        None,
                    )
                    replacement_for = next(
                        (
                            item for item in absences
                            if item["start"] <= iso <= item["end"]
                            and _display_name(item.get("replacement_name", "")) == name
                        ),
                        None,
                    )
                    manual = next(
                        (
                            override for override in day_overrides
                            if override.get("date") == iso
                            and override.get("staff_name") == name
                        ),
                        None,
                    )
                    incoming_manual = next(
                        (
                            override for override in day_overrides
                            if override.get("date") == iso
                            and override.get("status") == "work"
                            and _display_name(override.get("replaces_name", "")) == name
                        ),
                        None,
                    )
                    tooltip = f"{current.strftime('%d.%m.%Y')} · {name}"
                    if not member["active"]:
                        code, color = "—", "#F1F5F9"
                        tooltip += "\nНе участвует в планировании"
                    elif manual:
                        if manual.get("status") == "work":
                            code, color = "С", "#60A5FA"
                            replaced = _display_name(manual.get("replaces_name", ""))
                            tooltip += "\nРучная рабочая смена"
                            if replaced:
                                tooltip += f"\nРаботает вместо: {replaced}"
                        else:
                            code, color = "В", "#94A3B8"
                            tooltip += "\nРучной выходной"
                        if manual.get("reason"):
                            tooltip += f"\nПричина: {manual['reason']}"
                    elif absence:
                        code, color = self._absence_code(absence["absence_type"])
                        tooltip += f"\n{absence['absence_type']}"
                        if absence.get("replacement_name"):
                            tooltip += f"\nЕго заменяет: {_display_name(absence['replacement_name'])}"
                        else:
                            tooltip += "\nЗамена не назначена"
                    elif incoming_manual:
                        code, color = "В", "#CBD5E1"
                        tooltip += f"\nСмену выполняет: {incoming_manual['staff_name']}"
                        if incoming_manual.get("reason"):
                            tooltip += f"\nПричина: {incoming_manual['reason']}"
                    elif replacement_for:
                        replaced_name = replacement_for["staff_name"]
                        replaced_member = staff_by_name.get(replaced_name)
                        replaced_mode = replaced_member.get("work_mode") if replaced_member else ""
                        if replaced_mode == "day":
                            code, color = (
                                ("Д", "#86EFAC") if current.weekday() < 5 else ("В", "#CBD5E1")
                            )
                        elif replaced_mode.startswith("shift_"):
                            code, color = (
                                ("С", "#93C5FD") if replaced_mode == planned_mode else ("В", "#CBD5E1")
                            )
                        else:
                            code, color = "С", "#93C5FD"
                        tooltip += f"\n{name} заменяет {replaced_name}"
                        tooltip += f"\nУнаследован график: {code}"
                    elif mode == "day":
                        code, color = ("Д", "#86EFAC") if current.weekday() < 5 else ("В", "#CBD5E1")
                        tooltip += "\nДневная работа" if code == "Д" else "\nВыходной"
                    else:
                        code, color = ("С", "#93C5FD") if mode == planned_mode else ("В", "#CBD5E1")
                        tooltip += "\nРабочая смена" if code == "С" else "\nМежсменный выходной"
                    item = QTableWidgetItem(code)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setFont(QFont("Segoe UI", font_size, QFont.Weight.DemiBold))
                    item.setBackground(QColor(color))
                    item.setForeground(QColor("#0F172A"))
                    item.setToolTip(tooltip)
                    item.setData(Qt.ItemDataRole.UserRole, name)
                    item.setData(Qt.ItemDataRole.UserRole + 1, iso)
                    self.month_table.setItem(row, day_number, item)
        finally:
            self.month_table.blockSignals(False)

    def _month_cell_double_clicked(self, row, column):
        if column <= 0:
            return
        self.month_table.clearSelection()
        item = self.month_table.item(row, column)
        if item:
            item.setSelected(True)
        self._update_selection_panel()

    @staticmethod
    def _configure_table(table):
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(36)
        table.setShowGrid(True)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_maximized_once", False):
            self._maximized_once = True
            QTimer.singleShot(0, self._maximize_and_refresh)

    def _maximize_and_refresh(self):
        self.showMaximized()
        QTimer.singleShot(0, self._refresh_month_table)

    def _create_date_edit(self, date_str):
        de = QDateEdit()
        de.setCalendarPopup(True)
        de.setDisplayFormat("dd.MM.yyyy")
        try:
            if date_str:
                d = datetime.strptime(date_str, "%Y-%m-%d")
                de.setDate(QDate(d.year, d.month, d.day))
            else:
                de.setDate(QDate.currentDate())
        except Exception:
            de.setDate(QDate.currentDate())
        return de

    def _load_data(self):
        from staff_schedule import list_absences, list_day_overrides, list_staff

        self.day_override_rows = list_day_overrides()
        self.staff_table.blockSignals(True)
        staff = list_staff()
        self.staff_table.setRowCount(0)
        for member in staff:
            self._add_staff_row(member)
        self.staff_table.blockSignals(False)
        self.table.setRowCount(0)
        for absence in self._expand_generic_absences(list_absences()):
            self._add_row(absence)
        self._update_summary()

    @staticmethod
    def _expand_generic_absences(absences):
        """Переводит старое «Любого сменного» в конкретного дежурного по дням."""
        expanded = []
        epoch = CONFIG.get("duty_epoch", date.today())
        for item in absences:
            if item.get("staff_name") != "Любого сменного":
                expanded.append(dict(item))
                continue
            start = date.fromisoformat(item["start"])
            end = date.fromisoformat(item["end"])
            segments = []
            current = start
            while current <= end:
                block = ((current - epoch).days // 2) % 2
                employee = CONFIG.get("executor_1") if block == 0 else CONFIG.get("executor_2")
                if segments and segments[-1]["staff_name"] == employee:
                    segments[-1]["end"] = current.isoformat()
                else:
                    segment = dict(item)
                    segment["staff_name"] = employee
                    segment["start"] = current.isoformat()
                    segment["end"] = current.isoformat()
                    segment["id"] = ""
                    segments.append(segment)
                current += timedelta(days=1)
            expanded.extend(segments)
        return expanded

    def _add_staff_row(self, member=None):
        member = member or {}
        row = self.staff_table.rowCount()
        self.staff_table.insertRow(row)
        active = QTableWidgetItem("Да" if member.get("active", True) else "Нет")
        active.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
        )
        active.setCheckState(
            Qt.CheckState.Checked if member.get("active", True) else Qt.CheckState.Unchecked
        )
        active.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.staff_table.setItem(row, 0, active)
        self.staff_table.setItem(row, 1, QTableWidgetItem(member.get("name", "")))
        mode = QComboBox()
        mode.addItem("Сменный 1", "shift_a")
        mode.addItem("Сменный 2", "shift_b")
        mode.addItem("Дневной", "day")
        index = mode.findData(member.get("work_mode", "day"))
        mode.setCurrentIndex(max(index, 0))
        self.staff_table.setCellWidget(row, 2, mode)
        self.staff_table.setItem(row, 3, QTableWidgetItem(member.get("role", "Наладчик КИПиА")))
        mode.currentIndexChanged.connect(self._update_summary)
        self.staff_table.setCurrentCell(row, 1)
        self._refresh_absence_staff_choices()
        self._update_summary()

    def _staff_names_from_table(self):
        names = []
        for row in range(self.staff_table.rowCount()):
            item = self.staff_table.item(row, 1)
            name = item.text().strip() if item else ""
            if name:
                names.append(name)
        return names

    def _on_staff_item_changed(self, item):
        if item.column() == 0:
            item.setText("Да" if item.checkState() == Qt.CheckState.Checked else "Нет")
        if item.column() == 1:
            self._refresh_absence_staff_choices()
        self._update_summary()

    def _refresh_absence_staff_choices(self):
        if not hasattr(self, "table"):
            return
        names = self._staff_names_from_table()
        for row in range(self.table.rowCount()):
            for column, allow_any in ((0, True), (4, False)):
                combo = self.table.cellWidget(row, column)
                if not isinstance(combo, QComboBox):
                    continue
                current = combo.currentText().strip()
                combo.blockSignals(True)
                combo.clear()
                if allow_any:
                    combo.addItem("Любого сменного")
                else:
                    combo.addItem("")
                combo.addItems(names)
                combo.setCurrentText(current)
                combo.blockSignals(False)

    def _update_summary(self, *_args):
        if not hasattr(self, "summary_label"):
            return
        active = 0
        shift = 0
        day = 0
        for row in range(self.staff_table.rowCount()):
            item = self.staff_table.item(row, 0)
            is_active = bool(item and item.checkState() == Qt.CheckState.Checked)
            if not is_active:
                continue
            active += 1
            mode = self.staff_table.cellWidget(row, 2)
            if mode and str(mode.currentData()).startswith("shift_"):
                shift += 1
            else:
                day += 1
        absences = self.table.rowCount() if hasattr(self, "table") else 0
        self.summary_label.setText(
            f"Работают: <b>{active}</b>  ·  сменных: <b>{shift}</b>  ·  дневных: <b>{day}</b>"
            f"  ·  отсутствий: <b>{absences}</b>"
        )
        self._refresh_month_table()

    def _delete_staff_row(self):
        row = self.staff_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Табель", "Сначала выберите сотрудника в таблице.")
            return
        name_item = self.staff_table.item(row, 1)
        name = name_item.text().strip() if name_item else ""
        self.staff_table.removeRow(row)
        self._refresh_absence_staff_choices()
        self._update_summary()
        if name:
            self.staff_table.setToolTip(
                f"{name} будет убран из активного состава после сохранения табеля."
            )

    def _delete_absence_row(self):
        if self.table.currentRow() < 0:
            QMessageBox.information(self, "Табель", "Сначала выберите отсутствие в таблице.")
            return
        self.table.removeRow(self.table.currentRow())
        self._update_summary()

    def _add_absence_for_selected_staff(self):
        row = self.staff_table.currentRow()
        item = self.staff_table.item(row, 1) if row >= 0 else None
        name = item.text().strip() if item else ""
        if not name:
            QMessageBox.information(
                self, "Табель", "Выберите сотрудника с заполненным ФИО."
            )
            return
        self._add_row({"staff_name": name, "absence_type": "Отпуск"})
        self.table.setCurrentCell(self.table.rowCount() - 1, 0)

    def _add_row(self, absence=None):
        absence = absence or {}
        r = self.table.rowCount()
        self.table.insertRow(r)
        staff_combo = QComboBox()
        staff_combo.addItem("Любого сменного")
        staff_combo.addItems(self._staff_names_from_table())
        staff_combo.setCurrentText(absence.get("staff_name", "Любого сменного"))
        self.table.setCellWidget(r, 0, staff_combo)
        kind_combo = QComboBox()
        from staff_schedule import ABSENCE_TYPES
        kind_combo.addItems(ABSENCE_TYPES)
        kind_combo.setCurrentText(absence.get("absence_type", "Отпуск"))
        self.table.setCellWidget(r, 1, kind_combo)
        start_edit = self._create_date_edit(absence.get("start", ""))
        end_edit = self._create_date_edit(absence.get("end", ""))
        start_edit.dateChanged.connect(
            lambda value, end=end_edit: end.setDate(value) if end.date() < value else None
        )
        self.table.setCellWidget(r, 2, start_edit)
        self.table.setCellWidget(r, 3, end_edit)
        replacement = QComboBox()
        replacement.setEditable(True)
        replacement.addItem("")
        replacement.addItems(self._staff_names_from_table())
        replacement.setCurrentText(absence.get("replacement_name", ""))
        self.table.setCellWidget(r, 4, replacement)
        self.table.setItem(r, 5, QTableWidgetItem(absence.get("note", "")))
        self.table.setItem(r, 6, QTableWidgetItem(str(absence.get("id", ""))))
        self.table.setCurrentCell(r, 0)
        today = date.today().isoformat()
        start = str(absence.get("start", ""))
        end = str(absence.get("end", ""))
        if start and end and start <= today <= end:
            for column in (5,):
                item = self.table.item(r, column)
                if item:
                    item.setBackground(QColor("#FEF3C7"))
        self._update_summary()

    @staticmethod
    def _delete_current(table):
        row = table.currentRow()
        if row >= 0:
            table.removeRow(row)

    def get_data(self):
        res = []
        for r in range(self.table.rowCount()):
            staff_combo = self.table.cellWidget(r, 0)
            kind_combo = self.table.cellWidget(r, 1)
            de_start = self.table.cellWidget(r, 2)
            de_end = self.table.cellWidget(r, 3)
            replacement = self.table.cellWidget(r, 4)
            note_item = self.table.item(r, 5)
            
            st = de_start.date().toString("yyyy-MM-dd") if de_start else ""
            en = de_end.date().toString("yyyy-MM-dd") if de_end else ""
            staff_name = staff_combo.currentText().strip() if staff_combo else ""
            kind = kind_combo.currentText().strip() if kind_combo else ""
            replacement_name = replacement.currentText().strip() if replacement else ""
            note = note_item.text().strip() if note_item else ""
            if st and en and staff_name:
                res.append({
                    "start": st, "end": en, "staff_name": staff_name,
                    "absence_type": kind, "replacement_name": replacement_name, "note": note,
                })
        return res

    def _staff_data(self):
        rows = []
        for row in range(self.staff_table.rowCount()):
            active_item = self.staff_table.item(row, 0)
            name_item = self.staff_table.item(row, 1)
            mode = self.staff_table.cellWidget(row, 2)
            role_item = self.staff_table.item(row, 3)
            rows.append({
                "name": name_item.text().strip() if name_item else "",
                "work_mode": mode.currentData() if mode else "day",
                "role": role_item.text().strip() if role_item else "Наладчик КИПиА",
                "active": active_item.checkState() == Qt.CheckState.Checked if active_item else True,
            })
        return rows

    def _save(self):
        from staff_schedule import replace_absences, replace_day_overrides
        try:
            replace_absences(self.get_data())
            replace_day_overrides(self.day_override_rows)
        except Exception as exc:
            QMessageBox.critical(self, "Табель не сохранён", str(exc))
            return
        super().accept()


class StaffCompositionDialog(QDialog):
    """Редактор состава; календарные изменения выполняются только в табеле."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Состав сотрудников")
        self.resize(980, 560)
        layout = QVBoxLayout(self)
        title = QLabel("Состав сотрудников и постоянные графики")
        title.setStyleSheet("font-size:18px;font-weight:700;color:#0F172A;")
        layout.addWidget(title)
        info = QLabel(
            "Здесь меняются только сотрудники и их постоянный режим. "
            "Отпуска, больничные и замещения отмечаются выделением дней в месячном табеле."
        )
        info.setWordWrap(True)
        info.setStyleSheet("background:#EFF6FF;border:1px solid #BFDBFE;padding:9px;border-radius:6px;")
        layout.addWidget(info)

        actions = QHBoxLayout()
        btn_add = QPushButton("＋ Добавить сотрудника")
        btn_add.setObjectName("btn_primary")
        btn_delete = QPushButton("Убрать выбранного")
        btn_add.clicked.connect(self._add_row)
        btn_delete.clicked.connect(self._delete_row)
        actions.addWidget(btn_add)
        actions.addStretch()
        actions.addWidget(btn_delete)
        layout.addLayout(actions)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Работает", "ФИО сотрудника", "График", "Должность"])
        ExecutorOverrideDialog._configure_table(self.table)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(42)
        layout.addWidget(self.table)

        from staff_schedule import list_staff
        for member in list_staff():
            self._add_row(member)

        footer = QHBoxLayout()
        note = QLabel("Нужен ровно один работающий «Сменный 1» и один «Сменный 2».")
        note.setStyleSheet("color:#64748B;")
        btn_save = QPushButton("Сохранить состав")
        btn_save.setObjectName("btn_success")
        btn_cancel = QPushButton("Отмена")
        btn_save.clicked.connect(self._save)
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(note)
        footer.addStretch()
        footer.addWidget(btn_save)
        footer.addWidget(btn_cancel)
        layout.addLayout(footer)

    def _add_row(self, member=None):
        member = member or {}
        row = self.table.rowCount()
        self.table.insertRow(row)
        active = QTableWidgetItem("Да" if member.get("active", True) else "Нет")
        active.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
        )
        active.setCheckState(Qt.CheckState.Checked if member.get("active", True) else Qt.CheckState.Unchecked)
        active.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 0, active)
        self.table.setItem(row, 1, QTableWidgetItem(member.get("name", "")))
        mode = QComboBox()
        mode.addItem("Сменный 1", "shift_a")
        mode.addItem("Сменный 2", "shift_b")
        mode.addItem("Дневной", "day")
        mode.setCurrentIndex(max(0, mode.findData(member.get("work_mode", "day"))))
        self.table.setCellWidget(row, 2, mode)
        self.table.setItem(row, 3, QTableWidgetItem(member.get("role", "Наладчик КИПиА")))
        self.table.setCurrentCell(row, 1)

    def _delete_row(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Состав", "Выберите сотрудника в таблице.")
            return
        self.table.removeRow(row)

    def _data(self):
        rows = []
        for row in range(self.table.rowCount()):
            active = self.table.item(row, 0)
            name = self.table.item(row, 1)
            mode = self.table.cellWidget(row, 2)
            role = self.table.item(row, 3)
            rows.append(
                {
                    "active": active.checkState() == Qt.CheckState.Checked if active else True,
                    "name": name.text().strip() if name else "",
                    "work_mode": mode.currentData() if mode else "day",
                    "role": role.text().strip() if role else "Наладчик КИПиА",
                }
            )
        return rows

    def _save(self):
        from staff_schedule import save_staff
        rows = self._data()
        shift_a = [row["name"] for row in rows if row["active"] and row["work_mode"] == "shift_a" and row["name"]]
        shift_b = [row["name"] for row in rows if row["active"] and row["work_mode"] == "shift_b" and row["name"]]
        if len(shift_a) != 1 or len(shift_b) != 1:
            QMessageBox.critical(
                self, "Состав не сохранён",
                "Укажите ровно одного работающего сотрудника «Сменный 1» и одного «Сменный 2».",
            )
            return
        previous = dict(CONFIG)
        try:
            save_staff(rows)
            CONFIG["executor_1"] = shift_a[0]
            CONFIG["executor_2"] = shift_b[0]
            save_config(CONFIG)
        except Exception as exc:
            CONFIG.clear()
            CONFIG.update(previous)
            QMessageBox.critical(self, "Состав не сохранён", str(exc))
            return
        self.accept()


class HistoryResetDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Сброс истории ППР")
        self.resize(460, 280)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Удаляются записи из «Учет_выполненных_ППР.txt»\n"
                "по дате выдачи в выбранном периоде.\n"
                "После сброса те же ППР снова попадут в массовую генерацию."
            )
        )
        hl_dates = QHBoxLayout()
        vl_start = QVBoxLayout()
        vl_start.addWidget(QLabel("С:"))
        self.dt_start = QDateEdit(QDate.currentDate())
        self.dt_start.setCalendarPopup(True)
        self.dt_start.setDisplayFormat("dd.MM.yyyy")
        vl_start.addWidget(self.dt_start)
        hl_dates.addLayout(vl_start)
        vl_end = QVBoxLayout()
        vl_end.addWidget(QLabel("По:"))
        self.dt_end = QDateEdit(QDate.currentDate().addDays(7))
        self.dt_end.setCalendarPopup(True)
        self.dt_end.setDisplayFormat("dd.MM.yyyy")
        vl_end.addWidget(self.dt_end)
        hl_dates.addLayout(vl_end)
        layout.addLayout(hl_dates)
        self.lbl_period = QLabel("")
        self.lbl_period.setStyleSheet("font-weight:bold;color:#E65100;font-size:13px;")
        self.lbl_period.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_period)
        self.dt_start.dateChanged.connect(self._sync)
        self.dt_end.dateChanged.connect(self._sync)
        self._sync()
        hl_btns = QHBoxLayout()
        btn_ok = QPushButton("⚠️ Сбросить историю")
        btn_ok.setObjectName("btn_warning")
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        hl_btns.addWidget(btn_ok)
        hl_btns.addWidget(btn_cancel)
        layout.addLayout(hl_btns)

    def _sync(self):
        s = self.dt_start.date()
        self.dt_end.setMinimumDate(s)
        if self.dt_end.date() < s:
            self.dt_end.setDate(s)
        e = self.dt_end.date()
        days = s.daysTo(e) + 1
        self.lbl_period.setText(
            f"Период: {s.toString('dd.MM.yyyy')} — {e.toString('dd.MM.yyyy')} ({days} дн.)"
        )


class AdminSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки автоматизации")
        self.resize(720, 650)
        layout = QVBoxLayout(self)

        from PyQt6.QtWidgets import QFormLayout
        form = QFormLayout()
        
        self.exec1 = QLineEdit(CONFIG.get("executor_1", ""))
        self.exec2 = QLineEdit(CONFIG.get("executor_2", ""))
        self.overflow_exec = QLineEdit(CONFIG.get("overflow_executor", ""))
        self.task1 = QLineEdit(CONFIG.get("task_1", ""))
        self.place1 = QLineEdit(CONFIG.get("place_1", ""))
        self.task2 = QLineEdit(CONFIG.get("task_2", ""))
        self.place2 = QLineEdit(CONFIG.get("place_2", ""))
        self.issuer = QLineEdit(CONFIG.get("task_issuer", ""))
        self.schedules_dir = QLineEdit(CONFIG.get("schedules_dir", "Графики"))
        self.max_ppr = QSpinBox()
        self.max_ppr.setRange(1, 10)
        self.max_ppr.setValue(int(CONFIG.get("max_ppr_per_day", 2)))
        self.validation_minutes = QSpinBox()
        self.validation_minutes.setRange(1, 1440)
        self.validation_minutes.setValue(max(1, int(CONFIG.get("ppr_validation_max_age_s", 900)) // 60))
        self.inventory_plan_enabled = QCheckBox("Добавлять ежедневный план базы приборов в ССЗ")
        self.inventory_plan_enabled.setChecked(CONFIG.get("inventory_daily_plan_enabled", True))
        self.inventory_plan_size = QSpinBox()
        self.inventory_plan_size.setRange(1, 20)
        self.inventory_plan_size.setValue(int(CONFIG.get("inventory_daily_plan_size", 6)))
        
        self.kip_epoch = QDateEdit()
        self.kip_epoch.setCalendarPopup(True)
        self.kip_epoch.setDisplayFormat("dd.MM.yyyy")
        ke = CONFIG.get("kip_epoch", date(2026, 1, 1))
        self.kip_epoch.setDate(QDate(ke.year, ke.month, ke.day))
        
        self.duty_epoch = QDateEdit()
        self.duty_epoch.setCalendarPopup(True)
        self.duty_epoch.setDisplayFormat("dd.MM.yyyy")
        de = CONFIG.get("duty_epoch", date(2026, 1, 1))
        self.duty_epoch.setDate(QDate(de.year, de.month, de.day))

        form.addRow("Сменный 1 (четные пары):", self.exec1)
        form.addRow("Сменный 2 (нечетные пары):", self.exec2)
        form.addRow("Резерв для избытка ППР:", self.overflow_exec)
        form.addRow("Задание обхода 1:", self.task1)
        form.addRow("Место обхода 1:", self.place1)
        form.addRow("Задание обхода 2:", self.task2)
        form.addRow("Место обхода 2:", self.place2)
        form.addRow("Выдал задание:", self.issuer)
        form.addRow("Папка графиков ППР:", self.schedules_dir)
        form.addRow("Максимум ППР человеку в день:", self.max_ppr)
        form.addRow("Актуальность анализа, минут:", self.validation_minutes)
        form.addRow("План наполнения базы:", self.inventory_plan_enabled)
        form.addRow("Приборов в плане на день:", self.inventory_plan_size)
        form.addRow("Эпоха КИП д-мм (5-й КИП):", self.kip_epoch)
        form.addRow("Эпоха смены (Сменный 1):", self.duty_epoch)
        
        layout.addLayout(form)

        btn_overrides = QPushButton("Изменить полный состав сотрудников…")
        btn_overrides.clicked.connect(self._show_overrides)
        layout.addWidget(btn_overrides)

        diagnostics_row = QHBoxLayout()
        btn_diagnostics = QPushButton("Проверить настройки и связи системы")
        btn_diagnostics.clicked.connect(self._run_diagnostics)
        diagnostics_row.addWidget(btn_diagnostics)
        diagnostics_row.addStretch()
        layout.addLayout(diagnostics_row)
        self.health_label = QLabel("Нажмите «Проверить», чтобы проверить графики, базы, Office и табель.")
        self.health_label.setWordWrap(True)
        self.health_label.setStyleSheet(
            "background:#F8FAFC;border:1px solid #CBD5E1;border-radius:6px;padding:10px;"
        )
        layout.addWidget(self.health_label)

        hl = QHBoxLayout()
        btn_save = QPushButton("Сохранить")
        btn_save.setObjectName("btn_success")
        btn_save.clicked.connect(self._save)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        hl.addWidget(btn_save)
        hl.addWidget(btn_cancel)
        layout.addLayout(hl)

    def _show_overrides(self):
        pending_names = (
            self.exec1.text().strip(),
            self.exec2.text().strip(),
            self.overflow_exec.text().strip(),
        )
        saved_names = (
            str(CONFIG.get("executor_1", "")).strip(),
            str(CONFIG.get("executor_2", "")).strip(),
            str(CONFIG.get("overflow_executor", "")).strip(),
        )
        if pending_names != saved_names:
            QMessageBox.information(
                self,
                "Сначала сохраните состав",
                "Фамилии в настройках изменены, но ещё не сохранены. "
                "Сохраните настройки, затем снова откройте состав сотрудников.",
            )
            return
        dlg = StaffCompositionDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.exec1.setText(str(CONFIG.get("executor_1", "")))
            self.exec2.setText(str(CONFIG.get("executor_2", "")))

    def _save(self):
        candidate = self._candidate_config()
        check = validate_config(candidate)
        if check["errors"]:
            QMessageBox.critical(
                self, "Настройки не сохранены", "\n".join(f"• {item}" for item in check["errors"])
            )
            return
        previous = dict(CONFIG)
        try:
            CONFIG.clear()
            CONFIG.update(candidate)
            save_config(CONFIG)
            from staff_schedule import ensure_staff_seeded
            ensure_staff_seeded()
        except Exception as exc:
            CONFIG.clear()
            CONFIG.update(previous)
            QMessageBox.critical(self, "Настройки не сохранены", str(exc))
            return
        self.accept()

    def _candidate_config(self):
        candidate = dict(CONFIG)
        candidate["executor_1"] = self.exec1.text().strip()
        candidate["executor_2"] = self.exec2.text().strip()
        candidate["overflow_executor"] = self.overflow_exec.text().strip()
        candidate["task_1"] = self.task1.text().strip()
        candidate["place_1"] = self.place1.text().strip()
        candidate["task_2"] = self.task2.text().strip()
        candidate["place_2"] = self.place2.text().strip()
        candidate["task_issuer"] = self.issuer.text().strip()
        candidate["schedules_dir"] = self.schedules_dir.text().strip()
        candidate["max_ppr_per_day"] = self.max_ppr.value()
        candidate["ppr_validation_max_age_s"] = self.validation_minutes.value() * 60
        candidate["inventory_daily_plan_enabled"] = self.inventory_plan_enabled.isChecked()
        candidate["inventory_daily_plan_size"] = self.inventory_plan_size.value()
        kq = self.kip_epoch.date()
        candidate["kip_epoch"] = date(kq.year, kq.month, kq.day)
        dq = self.duty_epoch.date()
        candidate["duty_epoch"] = date(dq.year, dq.month, dq.day)
        return candidate

    def _run_diagnostics(self):
        result = run_system_diagnostics(self._candidate_config())
        lines = []
        if result.get("ok"):
            lines.extend(f"✓ {item}" for item in result["ok"])
        if result.get("warnings"):
            lines.extend(f"⚠ {item}" for item in result["warnings"])
        if result.get("errors"):
            lines.extend(f"✗ {item}" for item in result["errors"])
            color = "#991B1B"
            background = "#FEF2F2"
        else:
            color = "#166534"
            background = "#F0FDF4"
        self.health_label.setText("\n".join(lines) or "Проверка завершена без сообщений")
        self.health_label.setStyleSheet(
            f"background:{background};color:{color};border:1px solid {color};border-radius:6px;padding:10px;"
        )
