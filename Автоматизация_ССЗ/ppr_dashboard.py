import os
import calendar
from datetime import datetime, date

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QScrollArea, QFrame, QProgressBar, QMessageBox, QGridLayout, QComboBox,
    QCheckBox, QDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QColor, QPalette

from ssz_worker import ScheduleAnalysisWorker
from ssz_schedule import (
    get_filtered_history,
    get_ppr_history_records,
    make_signature,
    record_completed_tasks,
    record_issued_tasks,
    record_not_completed_tasks,
)
from ssz_utils import get_executor
from ppr_printer import PprPrintDialog, ppr_form_for_task


class PprDashboardWidget(QWidget):
    go_home = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PprDashboardWidget")
        self.worker = None
        self._print_selection = {}
        self._print_checkboxes = []
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(16)

        # Header
        header_layout = QHBoxLayout()
        self.btn_back = QPushButton("← Назад")
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back.clicked.connect(self.go_home.emit)
        
        title = QLabel("Дашборд ППР")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #2C3E50;")
        
        self.btn_refresh = QPushButton("Обновить")
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.load_data)

        self.btn_print = QPushButton("🖨 Печать бланков")
        self.btn_print.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_print.clicked.connect(self._show_print_dialog)

        header_layout.addWidget(self.btn_back)
        header_layout.addStretch()
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_print)
        header_layout.addWidget(self.btn_refresh)
        
        self.main_layout.addLayout(header_layout)

        # Month/Year selection
        month_selector_layout = QHBoxLayout()
        month_selector_layout.addStretch()
        
        lbl_m = QLabel("Месяц:")
        lbl_m.setStyleSheet("font-size: 14px; color: #495057;")
        self.combo_month = QComboBox()
        self.combo_month.setStyleSheet("font-size: 14px;")
        month_names = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                       "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
        self.combo_month.addItems(month_names)
        
        lbl_y = QLabel("Год:")
        lbl_y.setStyleSheet("font-size: 14px; color: #495057;")
        self.combo_year = QComboBox()
        self.combo_year.setStyleSheet("font-size: 14px;")
        
        current_year = date.today().year
        for y in range(current_year - 2, current_year + 3):
            self.combo_year.addItem(str(y))
            
        today = date.today()
        self.combo_month.setCurrentIndex(today.month - 1)
        self.combo_year.setCurrentText(str(today.year))
        
        self.combo_month.currentIndexChanged.connect(self.on_month_changed)
        self.combo_year.currentIndexChanged.connect(self.on_month_changed)

        month_selector_layout.addWidget(lbl_m)
        month_selector_layout.addWidget(self.combo_month)
        month_selector_layout.addSpacing(10)
        month_selector_layout.addWidget(lbl_y)
        month_selector_layout.addWidget(self.combo_year)
        month_selector_layout.addStretch()
        
        self.main_layout.addLayout(month_selector_layout)

        # Summary Metric Cards
        self.metrics_container = QWidget()
        m_layout = QHBoxLayout(self.metrics_container)
        m_layout.setContentsMargins(0, 0, 0, 0)
        m_layout.setSpacing(12)

        self.card_missed = QFrame()
        self.card_missed.setStyleSheet("QFrame { background: #FFE3E3; border: 1px solid #FFA8A8; border-radius: 8px; padding: 8px; }")
        l1 = QVBoxLayout(self.card_missed)
        self.lbl_missed_cnt = QLabel("🔴 Пропущено: 0")
        self.lbl_missed_cnt.setStyleSheet("font-size: 14px; font-weight: bold; color: #C92A2A;")
        self.lbl_missed_cnt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l1.addWidget(self.lbl_missed_cnt)

        self.card_upcoming = QFrame()
        self.card_upcoming.setStyleSheet("QFrame { background: #E7F5FF; border: 1px solid #A5D8FF; border-radius: 8px; padding: 8px; }")
        l2 = QVBoxLayout(self.card_upcoming)
        self.lbl_upcoming_cnt = QLabel("🔵 Предстоит: 0")
        self.lbl_upcoming_cnt.setStyleSheet("font-size: 14px; font-weight: bold; color: #1971C2;")
        self.lbl_upcoming_cnt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l2.addWidget(self.lbl_upcoming_cnt)

        self.card_completed = QFrame()
        self.card_completed.setStyleSheet("QFrame { background: #EBFBEE; border: 1px solid #B2F2BB; border-radius: 8px; padding: 8px; }")
        l3 = QVBoxLayout(self.card_completed)
        self.lbl_completed_cnt = QLabel("✅ Выполнено: 0")
        self.lbl_completed_cnt.setStyleSheet("font-size: 14px; font-weight: bold; color: #2B8A3E;")
        self.lbl_completed_cnt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l3.addWidget(self.lbl_completed_cnt)

        self.card_issued = QFrame()
        self.card_issued.setStyleSheet("QFrame { background: #FFF4E6; border: 1px solid #FFD8A8; border-radius: 8px; padding: 8px; }")
        l4 = QVBoxLayout(self.card_issued)
        self.lbl_issued_cnt = QLabel("🟠 Выдано: 0")
        self.lbl_issued_cnt.setStyleSheet("font-size: 14px; font-weight: bold; color: #D9480F;")
        self.lbl_issued_cnt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l4.addWidget(self.lbl_issued_cnt)

        self.card_not_completed = QFrame()
        self.card_not_completed.setStyleSheet("QFrame { background: #FEF2F2; border: 1px solid #FCA5A5; border-radius: 8px; padding: 8px; }")
        l5 = QVBoxLayout(self.card_not_completed)
        self.lbl_not_completed_cnt = QLabel("↩ Не выполнено: 0")
        self.lbl_not_completed_cnt.setStyleSheet("font-size: 14px; font-weight: bold; color: #B91C1C;")
        self.lbl_not_completed_cnt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l5.addWidget(self.lbl_not_completed_cnt)

        m_layout.addWidget(self.card_missed)
        m_layout.addWidget(self.card_upcoming)
        m_layout.addWidget(self.card_issued)
        m_layout.addWidget(self.card_not_completed)
        m_layout.addWidget(self.card_completed)
        self.main_layout.addWidget(self.metrics_container)

        self.print_selection_bar = QFrame()
        self.print_selection_bar.setStyleSheet(
            "QFrame { background:#F8FAFC;border:1px solid #CBD5E1;border-radius:7px; }"
        )
        print_bar_layout = QHBoxLayout(self.print_selection_bar)
        print_bar_layout.setContentsMargins(10, 7, 10, 7)
        self.lbl_print_selected = QLabel("Для печати выбрано: 0")
        self.lbl_print_selected.setStyleSheet("font-weight:600;color:#334155;")
        self.btn_select_printable = QPushButton("Выбрать все к выдаче")
        self.btn_select_printable.clicked.connect(self._select_all_printable)
        self.btn_clear_printable = QPushButton("Снять выбор")
        self.btn_clear_printable.clicked.connect(self._clear_print_selection)
        self.btn_print_selected = QPushButton("🖨 Распечатать выбранные ППР")
        self.btn_print_selected.setObjectName("btn_success")
        self.btn_print_selected.setEnabled(False)
        self.btn_print_selected.clicked.connect(self._print_selected_ppr)
        print_bar_layout.addWidget(self.lbl_print_selected)
        print_bar_layout.addStretch()
        print_bar_layout.addWidget(self.btn_select_printable)
        print_bar_layout.addWidget(self.btn_clear_printable)
        print_bar_layout.addWidget(self.btn_print_selected)
        self.main_layout.addWidget(self.print_selection_bar)

        # Loading Indicator
        self.loading_container = QWidget()
        loading_layout = QVBoxLayout(self.loading_container)
        self.lbl_loading = QLabel("Загрузка графиков ППР...")
        self.lbl_loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0) # Indeterminate
        self.progress_bar.setFixedHeight(12)
        loading_layout.addWidget(self.lbl_loading)
        loading_layout.addWidget(self.progress_bar)
        loading_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.loading_container)

        # Content Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #CED4DA; border-radius: 4px; background: white; }
            QTabBar::tab { background: #F8F9FA; border: 1px solid #CED4DA; padding: 8px 16px; margin-right: 2px; border-top-left-radius: 4px; border-top-right-radius: 4px; }
            QTabBar::tab:selected { background: #FFFFFF; border-bottom-color: #FFFFFF; font-weight: bold; }
        """)
        self.main_layout.addWidget(self.tabs)
        self.tabs.hide()

    def showEvent(self, event):
        super().showEvent(event)
        if self.worker is None or not self.worker.isRunning():
            self.load_data()

    def on_month_changed(self):
        if hasattr(self, '_data_loaded') and self._data_loaded:
            self.load_data()

    def load_data(self):
        self._print_selection.clear()
        self._print_checkboxes.clear()
        self._update_print_selection_ui()
        self.tabs.hide()
        self.loading_container.show()
        
        today = date.today()
        self.current_month = self.combo_month.currentIndex() + 1
        self.current_year = int(self.combo_year.currentText())
        
        if self.current_year < today.year or (self.current_year == today.year and self.current_month < today.month):
            self.today_day = 32
        elif self.current_year > today.year or (self.current_year == today.year and self.current_month > today.month):
            self.today_day = 0
        else:
            self.today_day = today.day

        # История исключается из распределения, но анализатор всё равно
        # перепроверяет цвета её исходных ячеек для очистки дашборда.
        _, completed_sigs = get_filtered_history(set())
        self.worker = ScheduleAnalysisWorker(
            months=[self.current_month], completed_signatures=completed_sigs,
            month_years={self.current_month: self.current_year},
            target_days={
                self.current_month: min(
                    max(self.today_day, 1),
                    calendar.monthrange(self.current_year, self.current_month)[1],
                )
            },
        )
        self.worker.finished_ok.connect(self.on_data_loaded)
        self.worker.error.connect(self.on_data_error)
        self.worker.start()

    def on_data_error(self, err_msg):
        self.loading_container.hide()
        QMessageBox.critical(self, "Ошибка загрузки", f"Не удалось загрузить графики: {err_msg}")

    def on_data_loaded(self, result):
        self._data_loaded = True
        self.loading_container.hide()
        self.tabs.clear()
        self.tabs.show()

        month_sch = result.get("month_schedules", {}).get(self.current_month, {})
        colored_canonicals = {
            make_signature(
                item.get("place", ""), item.get("day", 0), item.get("work", ""),
                plan_month=item.get("month"), plan_year=item.get("year", self.current_year),
            )
            for item in result.get("colored_skipped", [])
        }
        history_records = [
            record for record in get_ppr_history_records()
            if record["task"].get("plan_month") == self.current_month
            and record["task"].get("plan_year") == self.current_year
            and record["canonical"] not in colored_canonicals
        ]
        history_by_canonical = {record["canonical"]: record for record in history_records}
        
        # We need to distribute tasks by Executor
        workers_data = {}
        
        for day, tasks in month_sch.items():
            if not tasks:
                continue
            dt = date(self.current_year, self.current_month, day)
            for task in tasks:
                task_copy = dict(task)
                task_copy['assigned_date'] = dt
                canonical = make_signature(
                    task_copy["place"], task_copy["plan_day"], task_copy["work"],
                    plan_month=self.current_month, plan_year=self.current_year,
                )
                if canonical in history_by_canonical:
                    continue
                executor = task.get("executor") or get_executor(dt)
                task_copy["executor"] = executor
                if executor not in workers_data:
                    workers_data[executor] = {"upcoming": [], "missed": [], "issued": [], "not_completed": [], "completed": [], "cancelled": []}
                
                if day < self.today_day:
                    workers_data[executor]["missed"].append(task_copy)
                else:
                    workers_data[executor]["upcoming"].append(task_copy)

        # Now let's handle completed tasks that were skipped by ScheduleAnalysisWorker
        # We need to extract them from History
        for record in history_records:
            history_task = dict(record["task"])
            dt = history_task["assigned_date"]
            executor = history_task.get("executor") or get_executor(dt)
            if executor not in workers_data:
                workers_data[executor] = {"upcoming": [], "missed": [], "issued": [], "not_completed": [], "completed": [], "cancelled": []}
            bucket = {
                "Выдано": "issued",
                "Не выполнено": "not_completed",
                "Отменено": "cancelled",
            }.get(record["status"], "completed")
            workers_data[executor][bucket].append(history_task)

        # Calculate metrics totals
        tot_missed = sum(len(d["missed"]) for d in workers_data.values())
        tot_upcoming = sum(len(d["upcoming"]) for d in workers_data.values())
        tot_issued = sum(len(d["issued"]) for d in workers_data.values())
        tot_not_completed = sum(len(d["not_completed"]) for d in workers_data.values())
        tot_completed = sum(len(d["completed"]) for d in workers_data.values())

        self.lbl_missed_cnt.setText(f"🔴 Пропущено: {tot_missed}")
        self.lbl_upcoming_cnt.setText(f"🔵 Предстоит: {tot_upcoming}")
        self.lbl_issued_cnt.setText(f"🟠 Выдано: {tot_issued}")
        self.lbl_not_completed_cnt.setText(f"↩ Не выполнено: {tot_not_completed}")
        self.lbl_completed_cnt.setText(f"✅ Выполнено: {tot_completed}")

        # Sort executors alphabetically
        for executor in sorted(workers_data.keys()):
            data = workers_data[executor]
            if not any(data.values()):
                continue
                
            tab = QScrollArea()
            tab.setWidgetResizable(True)
            tab.setStyleSheet("QScrollArea { border: none; background: #F8F9FA; }")
            
            content = QWidget()
            content.setStyleSheet("background: #F8F9FA;")
            layout = QVBoxLayout(content)
            layout.setContentsMargins(16, 16, 16, 16)
            layout.setSpacing(20)

            if data["missed"]:
                layout.addWidget(self._create_section_label("🔴 Пропущенные (Прошедшие даты)", "#C92A2A"))
                for t in data["missed"]:
                    layout.addWidget(self._create_task_card(t, "missed"))

            if data["upcoming"]:
                layout.addWidget(self._create_section_label("🔵 Предстоящие", "#3B5BDB"))
                for t in sorted(data["upcoming"], key=lambda x: x["plan_day"]):
                    layout.addWidget(self._create_task_card(t, "upcoming"))

            if data["issued"]:
                layout.addWidget(self._create_section_label("🟠 Выданные", "#D9480F"))
                for t in sorted(data["issued"], key=lambda x: x["plan_day"]):
                    layout.addWidget(self._create_task_card(t, "issued"))

            if data["not_completed"]:
                layout.addWidget(self._create_section_label("↩ Не выполнено — требуется решение", "#B91C1C"))
                for t in sorted(data["not_completed"], key=lambda x: x["plan_day"]):
                    layout.addWidget(self._create_task_card(t, "not_completed"))
            
            if data["completed"]:
                layout.addWidget(self._create_section_label("✅ Выполненные", "#2B8A3E"))
                for t in sorted(data["completed"], key=lambda x: x["plan_day"]):
                    layout.addWidget(self._create_task_card(t, "completed"))

            if data["cancelled"]:
                layout.addWidget(self._create_section_label("⛔ Отменённые", "#64748B"))
                for t in sorted(data["cancelled"], key=lambda x: x["plan_day"]):
                    layout.addWidget(self._create_task_card(t, "cancelled"))

            layout.addStretch()
            tab.setWidget(content)
            
            # Count for tab title
            total_active = len(data["upcoming"]) + len(data["missed"]) + len(data["issued"]) + len(data["not_completed"])
            title = f"{executor} ({total_active})" if total_active > 0 else executor
            self.tabs.addTab(tab, title)
        self._update_print_selection_ui()

    def _create_section_label(self, text, color):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {color}; margin-top: 10px;")
        return lbl

    def _create_task_card(self, task, status):
        card = QFrame()
        card.setObjectName("TaskCard")
        
        bg_color = "#FFFFFF"
        border_color = "#CED4DA"
        if status == "missed":
            border_color = "#FFA8A8"
            bg_color = "#FFF5F5"
        elif status == "completed":
            border_color = "#B2F2BB"
            bg_color = "#F4FCE3"
        elif status == "issued":
            border_color = "#FFD8A8"
            bg_color = "#FFF4E6"
        elif status == "upcoming":
            border_color = "#A5D8FF"
            bg_color = "#E7F5FF"
        elif status == "not_completed":
            border_color = "#FCA5A5"
            bg_color = "#FEF2F2"
        elif status == "cancelled":
            border_color = "#CBD5E1"
            bg_color = "#F8FAFC"
            
        card.setStyleSheet(f"""
            QFrame#TaskCard {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
        """)
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        
        top_layout = QHBoxLayout()
        if status in ("missed", "upcoming", "not_completed", "issued"):
            check_print = QPushButton(
                "☐ Повторно в печать" if status == "issued" else "☐ Выбрать для печати"
            )
            check_print.setCheckable(True)
            check_print.setToolTip("Добавить один бланк для этого ППР в общий пакет печати")
            check_print.setStyleSheet(
                "QPushButton { background:#FFFFFF;color:#1D4ED8;border:2px solid #60A5FA;"
                "border-radius:6px;padding:7px 12px;font-weight:700;text-align:left; }"
                "QPushButton:hover { background:#EFF6FF; }"
                "QPushButton:checked { background:#DCFCE7;color:#166534;border-color:#22C55E; }"
            )
            check_print.toggled.connect(
                lambda checked, t=dict(task): self._set_task_print_selected(t, checked)
            )
            check_print.toggled.connect(
                lambda checked, button=check_print, repeated=status == "issued": button.setText(
                    "☑ Выбрано для повторной печати" if checked and repeated
                    else "☑ Выбрано для печати" if checked
                    else "☐ Повторно в печать" if repeated
                    else "☐ Выбрать для печати"
                )
            )
            self._print_checkboxes.append(check_print)
            top_layout.addWidget(check_print)
        dt = task.get("assigned_date", date.today())
        date_str = dt.strftime("%d.%m.%Y")
        lbl_date = QLabel(f"<b>Дата:</b> {date_str} (План: {task.get('plan_day')})")
        lbl_date.setStyleSheet("color: #495057;")
        
        lbl_place = QLabel(f"<b>Место:</b> {task.get('place')}")
        lbl_place.setStyleSheet("color: #495057;")
        
        top_layout.addWidget(lbl_date)
        top_layout.addWidget(lbl_place)
        top_layout.addStretch()
        layout.addLayout(top_layout)
        
        lbl_work = QLabel(task.get("work"))
        lbl_work.setWordWrap(True)
        lbl_work.setStyleSheet("font-size: 13px; color: #2C3E50; margin-top: 4px; margin-bottom: 4px;")
        layout.addWidget(lbl_work)
        
        if status in ("issued", "not_completed", "missed", "upcoming"):
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
        if status == "issued":
            btn_complete = QPushButton("✅ Отметить выполненным")
            btn_complete.setStyleSheet("""
                QPushButton {
                    background-color: #FFFFFF;
                    color: #2B8A3E;
                    border: 1px solid #2B8A3E;
                    border-radius: 4px;
                    padding: 4px 12px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #EBFBEE; }
            """)
            btn_complete.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_complete.clicked.connect(lambda _, t=task: self.mark_completed(t))
            btn_failed = QPushButton("↩ Не выполнено")
            btn_failed.clicked.connect(lambda _, t=task: self.mark_not_completed(t))
            btn_layout.addWidget(btn_complete)
            btn_layout.addWidget(btn_failed)
            layout.addLayout(btn_layout)
        elif status in ("not_completed", "missed", "upcoming"):
            btn_issue = QPushButton("📤 Выдать / выдать повторно")
            btn_issue.setObjectName("btn_primary")
            btn_issue.clicked.connect(lambda _, t=task: self.mark_issued(t))
            btn_layout.addWidget(btn_issue)
            if status == "not_completed":
                btn_complete = QPushButton("✅ Всё же выполнено")
                btn_complete.clicked.connect(lambda _, t=task: self.mark_completed(t))
                btn_layout.addWidget(btn_complete)
            layout.addLayout(btn_layout)
            
        return card

    @staticmethod
    def _print_task_key(task):
        return make_signature(
            task.get("place", ""),
            task.get("plan_day", task.get("original_day", 0)),
            task.get("work", ""),
            plan_month=task.get("plan_month"),
            plan_year=task.get("plan_year"),
        )

    def _set_task_print_selected(self, task, checked):
        key = self._print_task_key(task)
        if checked:
            self._print_selection[key] = dict(task)
        else:
            self._print_selection.pop(key, None)
        self._update_print_selection_ui()

    def _update_print_selection_ui(self):
        if not hasattr(self, "lbl_print_selected"):
            return
        count = len(self._print_selection)
        self.lbl_print_selected.setText(f"Для печати выбрано: {count}")
        self.btn_print_selected.setEnabled(count > 0)
        self.btn_clear_printable.setEnabled(count > 0)
        self.btn_select_printable.setEnabled(bool(self._print_checkboxes))

    def _select_all_printable(self):
        for checkbox in self._print_checkboxes:
            checkbox.setChecked(True)

    def _clear_print_selection(self):
        for checkbox in self._print_checkboxes:
            checkbox.setChecked(False)
        self._print_selection.clear()
        self._update_print_selection_ui()

    def _print_selected_ppr(self):
        tasks = list(self._print_selection.values())
        if not tasks:
            QMessageBox.information(self, "Печать ППР", "Отметьте галочками задания для печати.")
            return

        form_counts = {}
        unknown = []
        for task in tasks:
            form = ppr_form_for_task(task)
            if form is None:
                unknown.append(f"{task.get('place', 'Неизвестный цех')}: {task.get('work', '')}")
                continue
            _label, filename = form
            form_counts[filename] = form_counts.get(filename, 0) + 1
        if unknown:
            QMessageBox.warning(
                self,
                "Не определена форма ППР",
                "Для следующих заданий не удалось безопасно определить бланк:\n\n"
                + "\n".join(f"• {text}" for text in unknown)
                + "\n\nУточните цех в графике — печать пакета отменена.",
            )
            return

        dialog = PprPrintDialog(self, initial_counts=form_counts, lock_counts=True)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._clear_print_selection()
        QMessageBox.information(
            self,
            "Бланки ППР напечатаны",
            "Напечатаны только бланки. Статус заданий не изменён.\n\n"
            "ППР автоматически перейдут в «Выдано» только после печати ССЗ, в котором они действительно записаны.",
        )

    def mark_completed(self, task):
        try:
            assigned_dt = task.get("assigned_date", date.today())
            dt_str = assigned_dt.strftime("%d.%m.%Y")
            record_completed_tasks([(dt_str, [task])])
            # Reload data to reflect changes
            self.load_data()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить: {e}")

    def mark_not_completed(self, task):
        try:
            assigned_dt = task.get("assigned_date", date.today())
            record_not_completed_tasks([(assigned_dt.strftime("%d.%m.%Y"), [task])])
            self.load_data()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось вернуть ППР в работу: {e}")

    def mark_issued(self, task):
        try:
            issue_date = date.today()
            task = dict(task)
            task["assigned_day"] = issue_date.day
            task["assigned_date"] = issue_date
            if not task.get("executor"):
                task["executor"] = get_executor(issue_date)
            record_issued_tasks([(issue_date.strftime("%d.%m.%Y"), [task])])
            self.load_data()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось выдать ППР: {e}")

    def _show_print_dialog(self):
        dlg = PprPrintDialog(self)
        dlg.exec()
