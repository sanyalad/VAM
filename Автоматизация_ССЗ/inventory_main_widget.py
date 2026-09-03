import os
import difflib
import logging
from datetime import datetime, date

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QProgressBar, QMessageBox, QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem, QFileDialog, QHeaderView,
    QDialog, QLineEdit, QComboBox, QFormLayout, QListWidget, QListWidgetItem,
    QScrollArea, QFrame, QGridLayout, QAbstractItemView
    , QDateEdit, QCheckBox
)
from PyQt6.QtCore import Qt, QDate, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor

from inventory_db import (
    get_workshops, get_locations, get_devices, get_devices_for_calibration,
    replace_device, get_db_readiness_percentage, add_location, update_location, delete_location,
    update_device_location, get_unassigned_location, get_all_devices_full_info,
    get_inventory_stats, get_attention_items, get_attention_summary,
    ensure_daily_inventory_plan, get_daily_inventory_plan, update_daily_inventory_task,
    update_device_details,
)
from scheme_widget import SchemeEditorWidget
from checklist_dialog import ChecklistDialog

from inventory_workers import IngestWorker
from inventory_components import (
    SmartDeviceSelector, FurnaceSchemaDialog, WorkshopSchemeDialog,
    get_colored_date_html, format_date_ru
)
from toast_widget import Toast
from ssz_config import CONFIG, save_config
from telegram_inventory import (
    TelegramConnectionError, has_bot_token, load_bot_token, save_bot_token,
    send_attention_digest, test_connection,
)
from inventory_plan_printer import preview_daily_plan, print_daily_plan


class TelegramSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройка Telegram")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        info = QLabel(
            "Введите новый токен от @BotFather. Токен сохраняется в диспетчере "
            "учетных данных Windows и не записывается в config.json."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.token_input = QLineEdit()
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.setPlaceholderText(
            "Токен уже сохранен — оставьте пустым" if has_bot_token() else "123456789:AA..."
        )
        self.chat_id_input = QLineEdit(str(CONFIG.get("telegram_chat_id", "410689929")))
        self.chat_id_input.setPlaceholderText("Telegram chat_id")
        form.addRow("Токен бота:", self.token_input)
        form.addRow("Ваш chat_id:", self.chat_id_input)
        layout.addLayout(form)

        self.status_label = QLabel("Токен сохранен" if has_bot_token() else "Бот пока не подключен")
        self.status_label.setStyleSheet("color: #6B7280;")
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.test_button = QPushButton("Проверить и отправить тест")
        self.test_button.clicked.connect(self.test_telegram)
        save_button = QPushButton("Сохранить")
        save_button.setObjectName("btn_primary")
        save_button.clicked.connect(self.save_settings)
        cancel_button = QPushButton("Отмена")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.test_button)
        buttons.addStretch()
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

    def _current_token(self):
        return self.token_input.text().strip() or load_bot_token()

    def test_telegram(self):
        token = self._current_token()
        chat_id = self.chat_id_input.text().strip()
        if not token or not chat_id:
            QMessageBox.warning(self, "Telegram", "Укажите токен бота и chat_id.")
            return
        self.test_button.setEnabled(False)
        try:
            bot_name = test_connection(token, chat_id)
            self.status_label.setText(f"Подключение успешно: @{bot_name}")
            QMessageBox.information(self, "Telegram", "Тестовое сообщение отправлено.")
        except (TelegramConnectionError, ValueError) as exc:
            QMessageBox.critical(self, "Telegram", str(exc))
        finally:
            self.test_button.setEnabled(True)

    def save_settings(self):
        chat_id = self.chat_id_input.text().strip()
        if not chat_id:
            QMessageBox.warning(self, "Telegram", "Укажите chat_id.")
            return
        token = self.token_input.text().strip()
        try:
            if token:
                save_bot_token(token)
            elif not has_bot_token():
                QMessageBox.warning(self, "Telegram", "Введите новый токен бота.")
                return
        except (TelegramConnectionError, ValueError) as exc:
            QMessageBox.critical(self, "Telegram", str(exc))
            return
        CONFIG["telegram_chat_id"] = chat_id
        save_config(CONFIG)
        self.accept()


class InventoryDashboardWidget(QWidget):
    go_home = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InventoryDashboardWidget")
        self._attention_notified = False
        self.setup_ui()
        logging.info("InventoryDashboardWidget initialized.")
        
    def set_role(self, role):
        logging.info(f"Setting dashboard role: {role}")
        if role == "admin":
            self.btn_checklist.show()
        else:
            self.btn_checklist.hide()
            
    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(16)

        # Header
        header_layout = QHBoxLayout()
        self.btn_back = QPushButton("← Назад")
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back.clicked.connect(self.go_home.emit)
        
        title = QLabel("Учет приборов")
        title.setStyleSheet("font-size: 22px; font-weight: 700; color: #1F2937;")
        
        self.btn_checklist = QPushButton("📋 Задание на замену")
        self.btn_checklist.setObjectName("btn_success")
        self.btn_checklist.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_checklist.clicked.connect(self._open_checklist_dialog)

        self.btn_attention = QPushButton("Что нужно от меня: 0")
        self.btn_attention.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_attention.setStyleSheet(
            "QPushButton { background: #FFF7ED; color: #9A3412; border: 1px solid #FDBA74; "
            "border-radius: 6px; padding: 7px 12px; font-weight: 600; }"
            "QPushButton:hover { background: #FFEDD5; }"
        )
        self.btn_attention.clicked.connect(self.open_attention_tab)
        
        header_layout.addWidget(self.btn_back)
        header_layout.addStretch()
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_attention)
        header_layout.addWidget(self.btn_checklist)
        
        self.main_layout.addLayout(header_layout)

        # Сводка: пользователь сразу видит состояние учета, не открывая вкладки.
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(10)
        self.stat_labels = {}
        for key, caption, color in (
            ("total", "Всего приборов", "#2563EB"),
            ("in_storage", "В кладовках", "#0F766E"),
            ("due_soon", "Поверка ≤ 90 дней", "#D97706"),
            ("overdue", "Просрочено", "#DC2626"),
            ("unassigned", "Без места", "#7C3AED"),
        ):
            card = QFrame()
            card.setObjectName("inventoryStatCard")
            card.setStyleSheet(
                "QFrame#inventoryStatCard { background: #FFFFFF; border: 1px solid #E5E7EB; "
                f"border-left: 4px solid {color}; border-radius: 8px; }}"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 8, 12, 8)
            value = QLabel("0")
            value.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {color};")
            label = QLabel(caption)
            label.setStyleSheet("font-size: 11px; color: #6B7280;")
            card_layout.addWidget(value)
            card_layout.addWidget(label)
            stats_layout.addWidget(card, 1)
            self.stat_labels[key] = value
        self.main_layout.addLayout(stats_layout)

        self.lbl_latest_import = QLabel("Последняя сверка кладовки: данных пока нет")
        self.lbl_latest_import.setStyleSheet("font-size: 12px; color: #6B7280;")
        self.main_layout.addWidget(self.lbl_latest_import)
        
        # Readiness Progress
        progress_layout = QHBoxLayout()
        self.lbl_readiness = QLabel("Заполнение схем печей: 0%")
        self.lbl_readiness.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.progress_readiness = QProgressBar()
        self.progress_readiness.setRange(0, 100)
        self.progress_readiness.setValue(0)
        self.progress_readiness.setFixedHeight(15)
        
        progress_layout.addWidget(self.lbl_readiness)
        progress_layout.addWidget(self.progress_readiness)
        self.main_layout.addLayout(progress_layout)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #CED4DA; border-radius: 4px; background: white; }
            QTabBar::tab { background: #F8F9FA; border: 1px solid #CED4DA; padding: 8px 16px; margin-right: 2px; border-top-left-radius: 4px; border-top-right-radius: 4px; }
            QTabBar::tab:selected { background: #FFFFFF; border-bottom-color: #FFFFFF; font-weight: bold; }
        """)
        
        self.tab_structure = QWidget()
        self.tab_daily_plan = QWidget()
        self.tab_attention = QWidget()
        self.tab_search = QWidget()
        self.tab_tasks = QWidget()
        self.tab_upload = QWidget()
        self.tab_unassigned = QWidget()
        
        self.setup_tab_daily_plan()
        self.setup_tab_attention()
        self.setup_tab_structure()
        self.setup_tab_search()
        self.setup_tab_tasks()
        self.setup_tab_upload()
        self.setup_tab_unassigned()
        
        self.tabs.addTab(self.tab_daily_plan, "План на день")
        self.tabs.addTab(self.tab_attention, "Общая очередь")
        self.tabs.addTab(self.tab_structure, "Размещение")
        self.tabs.addTab(self.tab_search, "Поиск")
        self.tabs.addTab(self.tab_tasks, "Поверка")
        self.tabs.addTab(self.tab_unassigned, "Без места")
        self.tabs.addTab(self.tab_upload, "Импорт")
        
        self.main_layout.addWidget(self.tabs)

    def setup_tab_daily_plan(self):
        layout = QVBoxLayout(self.tab_daily_plan)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        top = QHBoxLayout()
        title = QLabel("Ежедневный план уточнения базы приборов")
        title.setStyleSheet("font-size:16px;font-weight:700;color:#1F2937;")
        self.daily_plan_date = QDateEdit(QDate.currentDate())
        self.daily_plan_date.setCalendarPopup(True)
        self.daily_plan_date.setDisplayFormat("dd.MM.yyyy")
        self.daily_plan_date.dateChanged.connect(self.refresh_daily_plan)
        top.addWidget(title)
        top.addStretch()
        top.addWidget(QLabel("Дата:"))
        top.addWidget(self.daily_plan_date)
        layout.addLayout(top)

        daily_size = int(CONFIG.get("inventory_daily_plan_size", 6))
        info = QLabel(
            f"На день предлагается до {daily_size} приборов только из одного цеха — это около "
            f"{daily_size * 5} приборов за рабочую неделю без перегрузки. Выберите строку, ответьте на вопрос "
            "по прибору или печи и сохраните — система сама перейдёт к следующему. "
            "Печатный план остаётся отдельным от ССЗ."
        )
        info.setWordWrap(True)
        info.setStyleSheet("background:#EFF6FF;border:1px solid #BFDBFE;padding:9px;border-radius:6px;")
        layout.addWidget(info)

        self.daily_focus_frame = QFrame()
        self.daily_focus_frame.setObjectName("dailyFocusFrame")
        self.daily_focus_frame.setStyleSheet(
            "QFrame#dailyFocusFrame { background:#F8FAFC;border:1px solid #94A3B8;"
            "border-radius:8px; }"
        )
        focus_layout = QVBoxLayout(self.daily_focus_frame)
        focus_layout.setContentsMargins(12, 10, 12, 10)
        focus_top = QHBoxLayout()
        self.daily_workshop_label = QLabel("Цех на сегодня: —")
        self.daily_workshop_label.setStyleSheet("font-size:15px;font-weight:700;color:#0F172A;")
        self.daily_progress = QProgressBar()
        self.daily_progress.setMinimumWidth(220)
        self.daily_progress.setFormat("Готово: %v из %m")
        focus_top.addWidget(self.daily_workshop_label)
        focus_top.addStretch()
        focus_top.addWidget(self.daily_progress)
        focus_layout.addLayout(focus_top)

        self.daily_question = QLabel("Выберите прибор в плане ниже")
        self.daily_question.setWordWrap(True)
        self.daily_question.setStyleSheet(
            "background:#FFF7ED;border:1px solid #FDBA74;color:#9A3412;"
            "padding:8px;border-radius:5px;font-weight:600;"
        )
        focus_layout.addWidget(self.daily_question)

        answer_grid = QGridLayout()
        self.daily_serial_input = QLineEdit()
        self.daily_serial_input.setPlaceholderText("Заводской номер")
        self.daily_calibration_input = QLineEdit()
        self.daily_calibration_input.setPlaceholderText("дд.мм.гггг")
        self.daily_location_combo = QComboBox()
        self.daily_position_input = QLineEdit()
        self.daily_position_input.setPlaceholderText("Позиция на печи / схеме")
        answer_grid.addWidget(QLabel("Зав. номер:"), 0, 0)
        answer_grid.addWidget(self.daily_serial_input, 0, 1)
        answer_grid.addWidget(QLabel("Дата поверки:"), 0, 2)
        answer_grid.addWidget(self.daily_calibration_input, 0, 3)
        answer_grid.addWidget(QLabel("Место / печь:"), 1, 0)
        answer_grid.addWidget(self.daily_location_combo, 1, 1)
        answer_grid.addWidget(QLabel("Позиция:"), 1, 2)
        answer_grid.addWidget(self.daily_position_input, 1, 3)
        answer_grid.setColumnStretch(1, 1)
        answer_grid.setColumnStretch(3, 1)
        focus_layout.addLayout(answer_grid)

        answer_actions = QHBoxLayout()
        self.btn_daily_save_next = QPushButton("Сохранить ответ и перейти к следующему →")
        self.btn_daily_save_next.setObjectName("btn_success")
        self.btn_daily_save_next.clicked.connect(self._save_daily_answer)
        self.btn_daily_unknown = QPushButton("Пока не удалось узнать")
        self.btn_daily_unknown.clicked.connect(lambda: self._set_daily_status("skipped"))
        answer_actions.addStretch()
        answer_actions.addWidget(self.btn_daily_unknown)
        answer_actions.addWidget(self.btn_daily_save_next)
        focus_layout.addLayout(answer_actions)
        layout.addWidget(self.daily_focus_frame)

        self.daily_plan_table = QTableWidget(0, 6)
        self.daily_plan_table.setHorizontalHeaderLabels(
            ["Печатать", "Приоритет", "Прибор", "Что узнать/сделать", "Место", "Состояние"]
        )
        self.daily_plan_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.daily_plan_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.daily_plan_table.verticalHeader().setVisible(False)
        header = self.daily_plan_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.daily_plan_table.itemChanged.connect(self._daily_plan_item_changed)
        self.daily_plan_table.currentCellChanged.connect(self._load_daily_editor)
        layout.addWidget(self.daily_plan_table)

        actions = QHBoxLayout()
        btn_refresh = QPushButton("Сформировать / обновить план")
        btn_refresh.setObjectName("btn_primary")
        btn_refresh.clicked.connect(self.refresh_daily_plan)
        btn_done = QPushButton("✅ Выполнено")
        btn_done.clicked.connect(lambda: self._set_daily_status("completed"))
        btn_skip = QPushButton("Пропустить")
        btn_skip.clicked.connect(lambda: self._set_daily_status("skipped"))
        btn_reopen = QPushButton("Вернуть в работу")
        btn_reopen.clicked.connect(lambda: self._set_daily_status("open"))
        btn_open = QPushButton("Открыть прибор")
        btn_open.clicked.connect(self._open_daily_device)
        btn_preview = QPushButton("👁 Предпросмотр листа")
        btn_preview.clicked.connect(self._preview_daily_plan)
        btn_print = QPushButton("🖨 Печать плана")
        btn_print.setObjectName("btn_success")
        btn_print.clicked.connect(self._print_daily_plan)
        actions.addWidget(btn_refresh)
        actions.addWidget(btn_done)
        actions.addWidget(btn_skip)
        actions.addWidget(btn_reopen)
        actions.addStretch()
        actions.addWidget(btn_open)
        actions.addWidget(btn_preview)
        actions.addWidget(btn_print)
        layout.addLayout(actions)
        self.daily_plan_summary = QLabel("")
        layout.addWidget(self.daily_plan_summary)
        self._updating_daily_plan = False
        self._daily_tasks_cache = []

    def _daily_date(self):
        qd = self.daily_plan_date.date()
        return date(qd.year(), qd.month(), qd.day())

    def refresh_daily_plan(self, *_args):
        if not hasattr(self, "daily_plan_table"):
            return
        tasks = ensure_daily_inventory_plan(self._daily_date())
        self._daily_tasks_cache = tasks
        self._updating_daily_plan = True
        try:
            self.daily_plan_table.setRowCount(len(tasks))
            labels = {"critical": "Критично", "high": "Нужны данные", "medium": "Запланировать"}
            statuses = {"open": "В работе", "completed": "Выполнено", "skipped": "Пропущено"}
            for row, task in enumerate(tasks):
                include = QTableWidgetItem("")
                include.setFlags(include.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                include.setCheckState(Qt.CheckState.Checked if task["include_in_print"] else Qt.CheckState.Unchecked)
                include.setData(Qt.ItemDataRole.UserRole, task["id"])
                include.setData(Qt.ItemDataRole.UserRole + 1, task["device_id"])
                self.daily_plan_table.setItem(row, 0, include)
                values = (
                    labels.get(task["priority"], task["priority"]),
                    f"{task['device_name']} · № {task['serial_number'] or 'не указан'}",
                    task["work"], task["place"], statuses.get(task["status"], task["status"]),
                )
                for column, value in enumerate(values, 1):
                    self.daily_plan_table.setItem(row, column, QTableWidgetItem(str(value)))
            open_count = sum(task["status"] == "open" for task in tasks)
            included = sum(task["status"] == "open" and task["include_in_print"] for task in tasks)
            self.daily_plan_summary.setText(
                f"Заданий: {len(tasks)} · в работе: {open_count} · выбрано для печати: {included}"
            )
            workshop = tasks[0].get("workshop_name", "—") if tasks else "—"
            done_count = sum(task["status"] != "open" for task in tasks)
            self.daily_workshop_label.setText(f"Цех на сегодня: {workshop}")
            self.daily_progress.setRange(0, max(len(tasks), 1))
            self.daily_progress.setValue(done_count)
        finally:
            self._updating_daily_plan = False
        if tasks:
            open_row = next((index for index, task in enumerate(tasks) if task["status"] == "open"), 0)
            self.daily_plan_table.setCurrentCell(open_row, 2)
            self._load_daily_editor(open_row, 2, -1, -1)
        else:
            self._clear_daily_editor("На эту дату задания не сформированы.")

    def _daily_question_text(self, task):
        return {
            "missing_calibration": "Найдите на приборе или в документах актуальную дату поверки.",
            "overdue": "Поверка просрочена. Укажите новую дату либо подтвердите, что данные ещё нужно искать.",
            "due_soon": "Проверьте дату следующей поверки и при необходимости уточните данные прибора.",
            "invalid_calibration": "Исправьте некорректную дату поверки.",
            "unassigned": "Укажите, в какой печи или месте установлен прибор, и его позицию на схеме.",
        }.get(task.get("issue_type"), "Уточните недостающие сведения по прибору.")

    def _clear_daily_editor(self, message="Выберите прибор в плане ниже"):
        self.daily_question.setText(message)
        self.daily_serial_input.clear()
        self.daily_calibration_input.clear()
        self.daily_location_combo.clear()
        self.daily_position_input.clear()
        self.btn_daily_save_next.setEnabled(False)
        self.btn_daily_unknown.setEnabled(False)

    def _load_daily_editor(self, current_row, _current_column=0, *_args):
        if self._updating_daily_plan or current_row < 0 or current_row >= len(self._daily_tasks_cache):
            return
        task = self._daily_tasks_cache[current_row]
        self.daily_question.setText(
            f"{task['device_name']} · {task.get('location_name') or 'место не указано'}\n"
            f"{self._daily_question_text(task)}"
        )
        self.daily_serial_input.setText(task.get("serial_number", ""))
        calibration = str(task.get("calibration_date") or "").split("T", 1)[0]
        try:
            calibration = datetime.strptime(calibration, "%Y-%m-%d").strftime("%d.%m.%Y")
        except ValueError:
            pass
        self.daily_calibration_input.setText(calibration)
        self.daily_position_input.setText(task.get("position", ""))
        self.daily_location_combo.clear()
        for location in get_locations(task.get("workshop_id")):
            prefix = "Печь" if location.get("type") == "furnace" else "Место"
            self.daily_location_combo.addItem(f"{prefix}: {location['name']}", location["id"])
        index = self.daily_location_combo.findData(task.get("location_id"))
        self.daily_location_combo.setCurrentIndex(max(index, 0))
        is_open = task.get("status") == "open"
        self.btn_daily_save_next.setEnabled(is_open)
        self.btn_daily_unknown.setEnabled(is_open)

    def _save_daily_answer(self):
        task_id, device_id = self._selected_daily_ids()
        if not task_id or not device_id:
            QMessageBox.information(self, "План на день", "Выберите прибор в списке.")
            return
        row = self.daily_plan_table.currentRow()
        task = self._daily_tasks_cache[row] if 0 <= row < len(self._daily_tasks_cache) else {}
        calibration_text = self.daily_calibration_input.text().strip()
        calibration_iso = None
        if calibration_text:
            parsed = None
            for pattern in ("%d.%m.%Y", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(calibration_text, pattern).date()
                    break
                except ValueError:
                    continue
            if parsed is None:
                QMessageBox.warning(
                    self, "Дата поверки", "Введите дату в формате ДД.ММ.ГГГГ, например 15.10.2027."
                )
                return
            calibration_iso = parsed.isoformat()
        issue_type = task.get("issue_type")
        if issue_type in ("missing_calibration", "invalid_calibration") and not calibration_iso:
            QMessageBox.warning(self, "Нужен ответ", "Для этой задачи необходимо указать корректную дату поверки.")
            return
        if issue_type == "overdue" and (not calibration_iso or parsed <= date.today()):
            QMessageBox.warning(
                self, "Нужен актуальный срок",
                "Просроченную поверку можно закрыть только актуальной датой позже сегодняшнего дня."
            )
            return
        selected_location = next(
            (
                location for location in get_locations(task.get("workshop_id"))
                if location["id"] == self.daily_location_combo.currentData()
            ),
            None,
        )
        if issue_type == "unassigned" and (
            selected_location is None or selected_location.get("type") == "unassigned"
        ):
            QMessageBox.warning(
                self, "Нужно место установки",
                "Выберите реальную печь или место установки. Раздел «Требуют распределения» не считается ответом."
            )
            return
        update_device_details(
            device_id,
            serial_number=self.daily_serial_input.text(),
            calibration_date=calibration_iso,
            location_id=self.daily_location_combo.currentData(),
            position=self.daily_position_input.text(),
        )
        update_daily_inventory_task(task_id, status="completed")
        self.refresh_daily_plan()
        self.refresh_attention()

    def _daily_plan_item_changed(self, item):
        if self._updating_daily_plan or item.column() != 0:
            return
        task_id = item.data(Qt.ItemDataRole.UserRole)
        if task_id:
            update_daily_inventory_task(
                task_id, include_in_print=item.checkState() == Qt.CheckState.Checked
            )
            self.refresh_daily_plan()

    def _daily_print_tasks(self):
        tasks = [
            task for task in get_daily_inventory_plan(self._daily_date())
            if task["status"] == "open" and task["include_in_print"]
        ]
        if not tasks:
            QMessageBox.information(
                self, "План на день", "Нет открытых заданий, отмеченных для печати."
            )
        return tasks

    def _preview_daily_plan(self):
        tasks = self._daily_print_tasks()
        if tasks:
            preview_daily_plan(self, self._daily_date(), tasks)

    def _print_daily_plan(self):
        tasks = self._daily_print_tasks()
        if tasks:
            print_daily_plan(self, self._daily_date(), tasks)

    def _selected_daily_ids(self):
        row = self.daily_plan_table.currentRow()
        if row < 0:
            return None, None
        item = self.daily_plan_table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole), item.data(Qt.ItemDataRole.UserRole + 1)

    def _set_daily_status(self, status):
        task_id, _device_id = self._selected_daily_ids()
        if not task_id:
            QMessageBox.information(self, "План на день", "Выберите задание.")
            return
        update_daily_inventory_task(task_id, status=status)
        self.refresh_daily_plan()
        self.refresh_attention()

    def _open_daily_device(self):
        _task_id, device_id = self._selected_daily_ids()
        device = next((entry for entry in self.all_devices_cache if entry.get("id") == device_id), None)
        if not device:
            QMessageBox.information(self, "План на день", "Выберите задание с прибором.")
            return
        self.search_input.setText(device.get("serial_number") or device.get("name") or "")
        self.search_location_filter.setCurrentIndex(0)
        self.tabs.setCurrentWidget(self.tab_search)
        self.perform_search()

    def setup_tab_attention(self):
        layout = QVBoxLayout(self.tab_attention)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        text_block = QVBoxLayout()
        title = QLabel("Рабочая очередь по учету приборов")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #1F2937;")
        subtitle = QLabel(
            "Здесь программа сама показывает, какие документы, даты или решения нужны от вас."
        )
        subtitle.setStyleSheet("color: #6B7280;")
        text_block.addWidget(title)
        text_block.addWidget(subtitle)
        title_row.addLayout(text_block)
        title_row.addStretch()

        self.attention_filter = QComboBox()
        self.attention_filter.addItem("Все задачи", "all")
        self.attention_filter.addItem("Критичные", "critical")
        self.attention_filter.addItem("Нужны данные", "high")
        self.attention_filter.addItem("Предстоящие", "medium")
        self.attention_filter.currentIndexChanged.connect(self.refresh_attention)
        title_row.addWidget(self.attention_filter)
        layout.addLayout(title_row)

        self.attention_summary = QLabel("")
        self.attention_summary.setStyleSheet(
            "background: #F9FAFB; border: 1px solid #E5E7EB; border-radius: 7px; "
            "padding: 9px 12px; color: #374151;"
        )
        layout.addWidget(self.attention_summary)

        self.attention_table = QTableWidget(0, 7)
        self.attention_table.setHorizontalHeaderLabels(
            ["Приоритет", "Что не так", "Прибор", "Заводской №", "Цех", "Место", "Что требуется"]
        )
        self.attention_table.setAlternatingRowColors(True)
        self.attention_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.attention_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.attention_table.verticalHeader().setVisible(False)
        self.attention_table.doubleClicked.connect(self.open_selected_attention_device)
        header = self.attention_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.attention_table)

        actions = QHBoxLayout()
        btn_open = QPushButton("Открыть выбранный прибор")
        btn_open.setObjectName("btn_primary")
        btn_open.clicked.connect(self.open_selected_attention_device)
        btn_import = QPushButton("Загрузить документ")
        btn_import.clicked.connect(lambda: self.tabs.setCurrentWidget(self.tab_upload))
        self.btn_send_telegram = QPushButton("Отправить в Telegram")
        self.btn_send_telegram.clicked.connect(self.send_attention_telegram)
        btn_telegram_settings = QPushButton("Настроить Telegram")
        btn_telegram_settings.clicked.connect(self.configure_telegram)
        btn_refresh = QPushButton("Обновить очередь")
        btn_refresh.clicked.connect(self.refresh_db)
        actions.addWidget(btn_open)
        actions.addWidget(btn_import)
        actions.addWidget(self.btn_send_telegram)
        actions.addWidget(btn_telegram_settings)
        actions.addStretch()
        actions.addWidget(btn_refresh)
        layout.addLayout(actions)

        self.attention_items_cache = []

    def open_attention_tab(self):
        self.tabs.setCurrentWidget(self.tab_attention)

    def configure_telegram(self):
        dialog = TelegramSettingsDialog(self)
        if dialog.exec():
            Toast.success(self, "Настройки Telegram сохранены.")

    def send_attention_telegram(self):
        chat_id = str(CONFIG.get("telegram_chat_id", "")).strip()
        if not has_bot_token() or not chat_id:
            QMessageBox.information(
                self,
                "Telegram",
                "Сначала нажмите «Настроить Telegram» и сохраните новый токен бота.",
            )
            self.configure_telegram()
            return
        self.btn_send_telegram.setEnabled(False)
        try:
            send_attention_digest(chat_id, get_attention_items())
            Toast.success(self, "Очередь задач отправлена в Telegram.")
        except (TelegramConnectionError, ValueError) as exc:
            QMessageBox.critical(self, "Telegram", str(exc))
        finally:
            self.btn_send_telegram.setEnabled(True)

    def open_selected_attention_device(self, *_args):
        row = self.attention_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Что нужно от меня", "Сначала выберите строку с прибором.")
            return
        item = self.attention_table.item(row, 0)
        device_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        device = next((entry for entry in self.all_devices_cache if entry.get("id") == device_id), None)
        if not device:
            QMessageBox.warning(self, "Что нужно от меня", "Прибор не найден. Обновите очередь.")
            return
        self.search_input.setText(device.get("serial_number") or device.get("name") or "")
        self.search_location_filter.setCurrentIndex(0)
        self.tabs.setCurrentWidget(self.tab_search)
        self.perform_search()

    def refresh_attention(self, *_args):
        items = get_attention_items()
        priority_filter = self.attention_filter.currentData() if hasattr(self, "attention_filter") else "all"
        self.attention_items_cache = items
        visible = items if priority_filter == "all" else [
            item for item in items if item["priority"] == priority_filter
        ]

        summary = get_attention_summary()
        self.attention_summary.setText(
            f"Всего: {summary['total']}   •   Критичные: {summary['critical']}   •   "
            f"Нужны данные: {summary['high']}   •   Предстоящие: {summary['medium']}"
        )
        self.btn_attention.setText(f"Что нужно от меня: {summary['total']}")
        self.attention_table.setRowCount(len(visible))
        priority_labels = {
            "critical": ("Критично", "#DC2626"),
            "high": ("Нужны данные", "#D97706"),
            "medium": ("Запланировать", "#2563EB"),
        }
        for row, entry in enumerate(visible):
            priority_text, priority_color = priority_labels.get(entry["priority"], (entry["priority"], "#374151"))
            values = (
                priority_text,
                entry["issue"],
                entry["device_name"],
                entry["serial_number"] or "—",
                entry["workshop_name"],
                entry["location_name"],
                entry["request"],
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setData(Qt.ItemDataRole.UserRole, entry["device_id"])
                self.attention_table.setItem(row, column, cell)
            self.attention_table.item(row, 0).setForeground(QColor(priority_color))
        
    def _open_checklist_dialog(self):
        logging.info("Opening checklist dialog from inventory dashboard.")
        dlg = ChecklistDialog(self)
        dlg.exec()
        if hasattr(self, 'refresh_db'):
            self.refresh_db()

        
    def setup_tab_structure(self):
        layout = QVBoxLayout(self.tab_structure)
        
        controls_layout = QHBoxLayout()
        self.btn_edit_scheme = QPushButton("⚙ Редактировать схему выбранного цеха")
        self.btn_edit_scheme.setObjectName("btn_secondary")
        self.btn_edit_scheme.clicked.connect(self.edit_workshop_scheme)
        
        btn_refresh = QPushButton("🔄 Обновить данные")
        btn_refresh.clicked.connect(self.refresh_db)
        
        controls_layout.addWidget(self.btn_edit_scheme)
        controls_layout.addStretch()
        
        legend_lbl = QLabel("<span style='color: #D32F2F;'>⬤</span> Просрочено   <span style='color: #F57C00;'>⬤</span> < 3 мес.   <span style='color: #388E3C;'>⬤</span> > 3 мес.")
        legend_lbl.setStyleSheet("font-size: 13px; font-weight: bold; background: #f8f9fa; padding: 4px 10px; border-radius: 6px; border: 1px solid #ddd;")
        controls_layout.addWidget(legend_lbl)
        
        controls_layout.addStretch()
        controls_layout.addWidget(btn_refresh)
        layout.addLayout(controls_layout)
        
        self.workshop_tabs = QTabWidget()
        self.workshop_tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab { padding: 6px 12px; margin-right: 2px; }
            QTabBar::tab:selected { font-weight: bold; background: #E7F5FF; border-bottom: 2px solid #4C6EF5; }
        """)
        layout.addWidget(self.workshop_tabs)
        self.workshop_trees = {}
        
    def setup_tab_tasks(self):
        layout = QVBoxLayout(self.tab_tasks)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.scroll_tasks = QScrollArea()
        self.scroll_tasks.setWidgetResizable(True)
        self.scroll_tasks.setFrameShape(QFrame.Shape.NoFrame)
        
        self.tasks_container = QWidget()
        self.tasks_layout = QVBoxLayout(self.tasks_container)
        self.tasks_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.tasks_layout.setSpacing(15)
        self.tasks_layout.setContentsMargins(20, 20, 20, 20)
        
        self.scroll_tasks.setWidget(self.tasks_container)
        layout.addWidget(self.scroll_tasks)
        
    def setup_tab_upload(self):
        layout = QVBoxLayout(self.tab_upload)
        
        lbl_info = QLabel(
            "Загрузите любой документ или фото сертификата поверки.\n"
            "Поддерживаются: Excel (.xlsx/.xls), Word (.docx), PDF, текст (.txt/.csv), "
            "изображения (.jpg/.png/.bmp/.tiff/.webp).\n\n"
            "• Графики ППР (Excel) — распознаются автоматически без ИИ\n"
            "• Остальные документы и фото — обработка через ИИ (нужен API-ключ в настройках)"
        )
        lbl_info.setWordWrap(True)
        layout.addWidget(lbl_info)
        
        self.upload_comment = QLineEdit()
        self.upload_comment.setPlaceholderText("Комментарий для ИИ (например: 'это приборы из 47-го цеха')... (необязательно)")
        self.upload_comment.setStyleSheet("font-size: 14px; padding: 8px; border: 1px solid #ccc; border-radius: 4px; margin-bottom: 10px;")
        layout.addWidget(self.upload_comment)
        
        self.btn_upload = QPushButton("Выбрать файл и обработать")
        self.btn_upload.setObjectName("btn_primary")
        self.btn_upload.clicked.connect(self.upload_file)
        layout.addWidget(self.btn_upload)
        
        self.lbl_upload_status = QLabel("")
        layout.addWidget(self.lbl_upload_status)
        layout.addStretch()

    def setup_tab_unassigned(self):
        layout = QVBoxLayout(self.tab_unassigned)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.scroll_unassigned = QScrollArea()
        self.scroll_unassigned.setWidgetResizable(True)
        self.scroll_unassigned.setFrameShape(QFrame.Shape.NoFrame)
        
        self.unassigned_container = QWidget()
        self.unassigned_layout = QVBoxLayout(self.unassigned_container)
        self.unassigned_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.unassigned_layout.setSpacing(15)
        self.unassigned_layout.setContentsMargins(20, 20, 20, 20)
        
        self.scroll_unassigned.setWidget(self.unassigned_container)
        layout.addWidget(self.scroll_unassigned)

    def setup_tab_search(self):
        layout = QVBoxLayout(self.tab_search)

        search_bar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Название, заводской номер, место или дата поверки…")
        self.search_input.setStyleSheet("font-size: 16px; padding: 10px; border: 1px solid #ccc; border-radius: 6px;")

        self.search_location_filter = QComboBox()
        self.search_location_filter.addItem("Все места", "all")
        self.search_location_filter.addItem("Кладовки", "storage")
        self.search_location_filter.addItem("Печи", "furnace")
        self.search_location_filter.addItem("УТИР", "utir")
        self.search_location_filter.addItem("Общие места", "general")
        self.search_location_filter.addItem("Без места", "unassigned")
        self.search_location_filter.setMinimumWidth(150)
        self.search_location_filter.currentIndexChanged.connect(self.perform_search)
        
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.perform_search)
        self.search_input.textChanged.connect(lambda: self.search_timer.start(300))
        
        search_bar.addWidget(self.search_input, 1)
        search_bar.addWidget(self.search_location_filter)
        layout.addLayout(search_bar)
        
        self.search_result_label = QLabel("Введите запрос или выберите тип места.")
        self.search_result_label.setStyleSheet("color: #6B7280; padding: 2px 4px;")
        layout.addWidget(self.search_result_label)

        self.search_table = QTableWidget(0, 7)
        self.search_table.setHorizontalHeaderLabels(
            ["Прибор", "Заводской №", "Цех", "Место", "Статус", "Позиция", "Поверка до"]
        )
        self.search_table.setAlternatingRowColors(True)
        self.search_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.search_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.search_table.setSortingEnabled(True)
        self.search_table.verticalHeader().setVisible(False)
        header = self.search_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.search_table)
        
        self.all_devices_cache = []

    def perform_search(self):
        query = self.search_input.text().strip().lower().replace('\t', ' ')
        location_filter = self.search_location_filter.currentData() if hasattr(self, "search_location_filter") else "all"
        
        self.search_table.setSortingEnabled(False)
        self.search_table.setRowCount(0)
                
        if not query and location_filter == "all":
            self.search_result_label.setText("Введите запрос или выберите тип места. Поиск работает по всем цехам.")
            self.search_table.setSortingEnabled(True)
            return
            
        def is_fuzzy_match(word, text):
            if word in text:
                return True
            if len(word) > 3:
                for t in text.replace("-", " ").replace(".", " ").split():
                    if difflib.SequenceMatcher(None, word, t).ratio() > 0.75:
                        return True
            return False

        def smart_match(q, text):
            for w in q.split():
                if not is_fuzzy_match(w, text):
                    return False
            return True
            
        results = []
        for d in self.all_devices_cache:
            if location_filter != "all" and d.get("location_type") != location_filter:
                continue
            sn = str(d['serial_number'] or '').lower()
            cal = str(d['calibration_date'] or '').lower()
            if cal:
                try:
                    parts = cal.split("-")
                    if len(parts) == 3:
                        ru_date = f"{parts[2]}.{parts[1]}.{parts[0]}"
                        cal += f" {ru_date}"
                except:
                    pass
            text = " ".join((
                str(d.get('name') or '').lower(), sn, cal,
                str(d.get('workshop_name') or '').lower(),
                str(d.get('location_name') or '').lower(),
                str(d.get('position') or '').lower(),
                str(d.get('lifecycle_status') or '').lower(),
            ))
            if not query or smart_match(query, text):
                results.append(d)
                
        if not results:
            self.search_result_label.setText("Ничего не найдено. Измените запрос или фильтр.")
            self.search_table.setSortingEnabled(True)
            return
            
        total_results = len(results)
        results = results[:50]
        self.search_result_label.setText(
            f"Найдено: {total_results}{' · показаны первые 50' if total_results > 50 else ''}"
        )
        
        self.search_table.setRowCount(len(results))
        for row, d in enumerate(results):
            values = (
                d.get("name") or "—",
                d.get("serial_number") or "—",
                d.get("workshop_name") or "—",
                d.get("location_name") or "—",
                "Выведено из эксплуатации" if d.get("lifecycle_status") == "out_of_service" else "В эксплуатации",
                d.get("position") or "—",
                format_date_ru(d.get("calibration_date")) if d.get("calibration_date") else "не указана",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, d.get("id"))
                self.search_table.setItem(row, column, item)
            date_value = d.get("calibration_date")
            status_item = self.search_table.item(row, 4)
            if d.get("lifecycle_status") == "out_of_service":
                status_item.setForeground(QColor("#DC2626"))
            else:
                status_item.setForeground(QColor("#15803D"))

            date_item = self.search_table.item(row, 6)
            if not date_value:
                date_item.setForeground(QColor("#6B7280"))
            else:
                try:
                    days_left = (datetime.strptime(date_value.split("T")[0], "%Y-%m-%d").date() - date.today()).days
                    date_item.setForeground(QColor("#DC2626" if days_left < 0 else "#D97706" if days_left <= 90 else "#15803D"))
                except (ValueError, AttributeError):
                    date_item.setForeground(QColor("#6B7280"))
        self.search_table.setSortingEnabled(True)
        
    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_db()
        if not self._attention_notified:
            summary = get_attention_summary()
            if summary["total"]:
                Toast.warning(
                    self,
                    f"По учету приборов требуется ваше внимание: {summary['total']} задач. "
                    "Откройте раздел «Что нужно от меня».",
                    duration_ms=7000,
                )
            self._attention_notified = True
        
    def _on_ws_tab_changed(self, index):
        if index < 0 or index in getattr(self, "loaded_tabs", set()):
            return
            
        self.loaded_tabs.add(index)
        ws = getattr(self, "cached_workshops", [])[index]
        scroll = self.workshop_tabs.widget(index)
        
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        if "92" in ws["name"]:
            ws_template = ["КСП-3", "Термопары"]
        else:
            ws_template = [
                "Расход газа (КСД-2)", 
                "Расход воздуха (КСД-2)", 
                "Температура в печи (КСП-4)", 
                "Температура гибких (аттестация) (КСП-4)", 
                "Давление в печи (КСД-2)",
                "Температура дыма и воздуха после рекуператора",
                "Температура дыма до рекуператора"
            ]
        
        locations = [l for l in self.cached_locations if l["workshop_id"] == ws["id"]]
        
        scheme_widget = SchemeEditorWidget(ws["id"], ws["name"], locations, self)
        scheme_widget.setMinimumHeight(400)
        scheme_widget.view.location_clicked.connect(self._on_scheme_location_clicked)
        layout.addWidget(scheme_widget)

        for loc in locations:
            if loc["type"] == "unassigned":
                continue
                
            loc_type = loc["type"]
            devices = [d for d in self.all_devices_cache if d["loc_id"] == loc["id"]]
            
            card = QFrame()
            card.setProperty("loc_id", loc["id"])
            card.setStyleSheet("QFrame { background: white; border-radius: 8px; border: 1px solid #ddd; }")
            card_lyt = QVBoxLayout(card)
            card_lyt.setContentsMargins(15, 15, 15, 15)
            card_lyt.setSpacing(10)
            
            type_display = {"furnace": "Печь", "utir": "УТИР", "storage": "Кладовка", "general": "Место"}.get(loc_type, "Место")
            lbl_title = QLabel(f"<b>{loc['name']}</b> ({type_display})")
            lbl_title.setStyleSheet("font-size: 18px; color: #2B2D42;")
            card_lyt.addWidget(lbl_title)
            
            if loc_type in ("furnace", "utir"):
                used_devices = set()
                grid = QGridLayout()
                grid.setSpacing(10)
                
                for row, slot in enumerate(ws_template):
                    lbl_slot = QLabel(f"<b>{slot}</b>:")
                    lbl_slot.setStyleSheet("font-size: 14px; color: #555;")
                    
                    device_info = None
                    for d in devices:
                        if d.get("position") == slot and d["id"] not in used_devices:
                            device_info = d
                            used_devices.add(d["id"])
                            break
                            
                    if device_info:
                        sn = device_info["serial_number"] or "нет номера"
                        cal_date_html = get_colored_date_html(device_info["calibration_date"])
                        
                        val_lyt = QHBoxLayout()
                        val_lyt.setContentsMargins(0, 0, 0, 0)
                        lbl_val = QLabel(f"{device_info['name']} (Зав.№: {sn}) | Поверка до: {cal_date_html}")
                        lbl_val.setStyleSheet("font-size: 14px; color: #111; font-weight: normal;")
                        btn_rm = QPushButton("Снять")
                        btn_rm.setStyleSheet("background-color: #f44336; color: white; padding: 2px 8px; border-radius: 3px;")
                        btn_rm.clicked.connect(lambda checked, d_id=device_info["id"], w_id=ws["id"]: self.unassign_device(d_id, w_id))
                        val_lyt.addWidget(lbl_val)
                        val_lyt.addWidget(btn_rm)
                        val_lyt.addStretch()
                        
                        val_widget = QWidget()
                        val_widget.setLayout(val_lyt)
                        grid.addWidget(lbl_slot, row, 0)
                        grid.addWidget(val_widget, row, 1)
                    else:
                        selector = SmartDeviceSelector(
                            available_devices=self.all_devices_cache, 
                            location_id=loc["id"], 
                            position=slot, 
                            parent_dashboard=self
                        )
                        grid.addWidget(lbl_slot, row, 0)
                        grid.addWidget(selector, row, 1)
                
                card_lyt.addLayout(grid)
                
                extra_devs = [d for d in devices if d["id"] not in used_devices]
                if extra_devs:
                    lbl_extra = QLabel("<b>Дополнительные приборы:</b>")
                    lbl_extra.setStyleSheet("margin-top: 10px; color: #777;")
                    card_lyt.addWidget(lbl_extra)
                    for ed in extra_devs:
                        sn = ed["serial_number"] or "нет номера"
                        pos_str = f" (Позиция: {ed['position']})" if ed.get('position') else ""
                        cal_date_html = get_colored_date_html(ed['calibration_date'])
                        
                        ed_lyt = QHBoxLayout()
                        ed_lyt.setContentsMargins(0, 0, 0, 0)
                        lbl_ed = QLabel(f"• {ed['name']} (Зав.№: {sn}){pos_str} | Поверка до: {cal_date_html}")
                        lbl_ed.setStyleSheet("font-size: 14px;")
                        btn_rm = QPushButton("Снять")
                        btn_rm.setStyleSheet("background-color: #f44336; color: white; padding: 2px 8px; border-radius: 3px;")
                        btn_rm.clicked.connect(lambda checked, d_id=ed["id"], w_id=ws["id"]: self.unassign_device(d_id, w_id))
                        ed_lyt.addWidget(lbl_ed)
                        ed_lyt.addWidget(btn_rm)
                        ed_lyt.addStretch()
                        
                        ed_widget = QWidget()
                        ed_widget.setLayout(ed_lyt)
                        card_lyt.addWidget(ed_widget)
            else:
                if not devices:
                    lbl_empty = QLabel("Нет приборов")
                    lbl_empty.setStyleSheet("color: #999;")
                    card_lyt.addWidget(lbl_empty)
                else:
                    for d in devices:
                        sn = d["serial_number"] or "нет номера"
                        pos_str = f" (Позиция: {d['position']})" if d.get('position') else ""
                        cal_date_html = get_colored_date_html(d['calibration_date'])
                        
                        d_lyt = QHBoxLayout()
                        d_lyt.setContentsMargins(0, 0, 0, 0)
                        lbl_d = QLabel(f"• {d['name']} (Зав.№: {sn}){pos_str} | Поверка до: {cal_date_html}")
                        lbl_d.setStyleSheet("font-size: 14px;")
                        btn_rm = QPushButton("Снять")
                        btn_rm.setStyleSheet("background-color: #f44336; color: white; padding: 2px 8px; border-radius: 3px;")
                        btn_rm.clicked.connect(lambda checked, d_id=d["id"], w_id=ws["id"]: self.unassign_device(d_id, w_id))
                        d_lyt.addWidget(lbl_d)
                        d_lyt.addWidget(btn_rm)
                        d_lyt.addStretch()
                        
                        d_widget = QWidget()
                        d_widget.setLayout(d_lyt)
                        card_lyt.addWidget(d_widget)
                    
            layout.addWidget(card)
            
        scroll.setWidget(container)

    def _on_scheme_location_clicked(self, loc_id, loc_name=None):
        logging.info(f"Scheme location clicked: loc_id={loc_id}, loc_name={loc_name}")
        loc = None
        if loc_id and loc_id != -1:
            loc = next((l for l in self.cached_locations if l["id"] == loc_id), None)
            
        if not loc and loc_name:
            clean_name = str(loc_name).strip()
            loc = next((l for l in self.cached_locations if l["name"].strip() == clean_name or clean_name in l["name"] or l["name"] in clean_name), None)

        curr_idx = self.workshop_tabs.currentIndex()
        ws_id = 1
        if curr_idx >= 0:
            ws_widget = self.workshop_tabs.widget(curr_idx)
            if hasattr(ws_widget, "property"):
                ws_id = ws_widget.property("ws_id") or 1

        if not loc and loc_name:
            clean_str = str(loc_name).strip()
            is_storage = any(k in clean_str.upper() for k in ["КЛ", "КЛАД", "МАСТ"])
            loc_type = "storage" if is_storage else "furnace"
            
            if any(k in clean_str.upper() for k in ["ПЕЧЬ", "КЛАДОВКА", "МАСТ", "УТИР", "КЛ-КА"]):
                full_name = clean_str
            else:
                full_name = f"Печь {clean_str}"

            try:
                from inventory_db import add_location
                new_id = add_location(ws_id, full_name, loc_type)
                self.cached_locations = get_locations()
                loc = next((l for l in self.cached_locations if l["id"] == new_id), None)
            except Exception as e:
                logging.error(f"Error auto-creating location on click: {e}")
                
            if not loc:
                loc = {"id": -1, "workshop_id": ws_id, "name": full_name, "type": loc_type}

        if not loc:
            logging.warning("No location could be resolved for scheme click.")
            return

        logging.info(f"Resolved location: id={loc['id']}, name={loc['name']}")

        # Highlight card in workshop scroll view if present
        if curr_idx >= 0:
            scroll = self.workshop_tabs.widget(curr_idx)
            if scroll:
                container = scroll.widget()
                if container:
                    for frame in container.findChildren(QFrame):
                        if frame.property("loc_id") == loc.get("id") or (loc_name and loc_name in str(frame.property("loc_id"))):
                            scroll.ensureWidgetVisible(frame)
                            frame.setStyleSheet("QFrame { background: #FFF9C4; border-radius: 8px; border: 2px solid #FF9800; }")
                            QTimer.singleShot(1500, lambda f=frame: f.setStyleSheet("QFrame { background: white; border-radius: 8px; border: 1px solid #ddd; }"))
                            break

        ws = next((w for w in getattr(self, "cached_workshops", []) if w["id"] == loc.get("workshop_id", ws_id)), None)
        ws_name = ws["name"] if ws else "Цех"
        
        if "92" in ws_name:
            ws_template = ["КСП-3", "Термопары"]
        else:
            ws_template = [
                "Расход газа (КСД-2)", 
                "Расход воздуха (КСД-2)", 
                "Температура в печи (КСП-4)", 
                "Температура гибких (аттестация) (КСП-4)", 
                "Давление в печи (КСД-2)",
                "Температура дыма и воздуха после рекуператора",
                "Температура дыма до рекуператора"
            ]
            
        target_id = loc.get("id", -1)
        devices = [d for d in self.all_devices_cache if d.get("loc_id") == target_id or d.get("location_id") == target_id]
        
        dialog = FurnaceSchemaDialog(ws_name, loc["name"], ws_template, devices, self)
        dialog.exec()

    def refresh_db(self):
        logging.info("Refreshing database in inventory dashboard.")
        self.all_devices_cache = get_all_devices_full_info()
        if hasattr(self, 'search_input') and self.search_input.text().strip():
            self.perform_search()
            
        pct = get_db_readiness_percentage()
        self.progress_readiness.setValue(int(pct))
        self.lbl_readiness.setText(f"Заполнение схем печей: {pct}%")

        stats = get_inventory_stats()
        for key, label in getattr(self, "stat_labels", {}).items():
            label.setText(str(stats.get(key, 0)))
        latest = stats.get("latest_import")
        if latest:
            imported_at = str(latest.get("imported_at") or "").replace("T", " ")[:16]
            self.lbl_latest_import.setText(
                f"Последняя сверка кладовки: {imported_at} · {latest['source_file']} · "
                f"{latest['rows_total']} строк ({latest['rows_added']} новых, {latest['rows_updated']} обновлено)"
            )
        else:
            self.lbl_latest_import.setText("Последняя сверка кладовки: данных пока нет")

        self.refresh_attention()
        self.refresh_daily_plan()

        self.workshop_tabs.clear()
        
        all_locations = get_locations()
        workshops = get_workshops()
        self.cached_workshops = workshops
        self.cached_locations = all_locations
        self.loaded_tabs = set()
        
        curr_idx = self.workshop_tabs.currentIndex()
        
        for idx, ws in enumerate(workshops):
            scroll = QScrollArea()
            scroll.setProperty("ws_id", ws["id"])
            scroll.setProperty("ws_name", ws["name"])
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            self.workshop_tabs.addTab(scroll, ws["name"])
            
        try:
            self.workshop_tabs.currentChanged.disconnect(self._on_ws_tab_changed)
        except Exception:
            pass
        self.workshop_tabs.currentChanged.connect(self._on_ws_tab_changed)
        
        target_idx = curr_idx if curr_idx >= 0 and curr_idx < len(workshops) else 0
        if len(workshops) > 0:
            self.workshop_tabs.setCurrentIndex(target_idx)
            self._on_ws_tab_changed(target_idx)
        
        # Populate Unassigned Tasks
        unassigned_devices = []
        for d in self.all_devices_cache:
            if "мэо" in d["name"].lower():
                continue
                
            is_unassigned = False
            if d["location_type"] == "unassigned":
                is_unassigned = True
            elif d["location_type"] in ("furnace", "utir"):
                if "92" in d["workshop_name"]:
                    tmpl_set = {"КСП-3", "Термопары"}
                else:
                    tmpl_set = {
                        "Расход газа (КСД-2)", 
                        "Расход воздуха (КСД-2)", 
                        "Температура в печи (КСП-4)", 
                        "Температура гибких (аттестация) (КСП-4)", 
                        "Давление в печи (КСД-2)",
                        "Температура дыма и воздуха после рекуператора",
                        "Температура дыма до рекуператора"
                    }
                if d.get("position") not in tmpl_set:
                    is_unassigned = True
                    
            if is_unassigned:
                d_copy = dict(d)
                d_copy["loc_type_origin"] = d["location_type"]
                d_copy["loc_name_origin"] = d["location_name"]
                unassigned_devices.append(d_copy)
                        
        while self.unassigned_layout.count():
            item = self.unassigned_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
                
        if not unassigned_devices:
            lbl_empty = QLabel("✅ Все приборы успешно распределены по своим местам!")
            lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_empty.setStyleSheet("font-size: 20px; font-weight: bold; color: #4CAF50; margin-top: 50px;")
            self.unassigned_layout.addWidget(lbl_empty)
        else:
            for d in unassigned_devices:
                card = QFrame()
                card.setStyleSheet("QFrame { background: white; border-radius: 8px; border: 1px solid #ddd; padding: 10px; }")
                card_lyt = QVBoxLayout(card)
                
                sn_str = d["serial_number"] if d["serial_number"] else "Нет"
                lbl_title = QLabel(f"<b>{d['name']}</b> (Зав. №: {sn_str})")
                lbl_title.setStyleSheet("font-size: 16px;")
                card_lyt.addWidget(lbl_title)
                
                pos_str = d["position"] if d["position"] else "Не указана"
                lbl_origin = QLabel(f"Извлечено из: <b>{d['workshop_name']}</b>, Место: <b>{d.get('loc_name_origin', 'Нераспределенные')}</b>, Исходная позиция: {pos_str}")
                lbl_origin.setStyleSheet("font-size: 13px; color: #555;")
                card_lyt.addWidget(lbl_origin)
                
                controls_lyt = QHBoxLayout()
                controls_lyt.setSpacing(10)
                
                lbl_ws = QLabel("Цех:")
                lbl_ws.setStyleSheet("font-weight: bold;")
                combo_ws = QComboBox()
                combo_ws.setStyleSheet("font-size: 14px; padding: 5px;")
                
                lbl_loc = QLabel("Место:")
                lbl_loc.setStyleSheet("font-weight: bold;")
                combo_loc = QComboBox()
                combo_loc.setStyleSheet("font-size: 14px; padding: 5px;")
                
                lbl_pos = QLabel("Позиция:")
                lbl_pos.setStyleSheet("font-weight: bold;")
                combo_pos = QComboBox()
                combo_pos.setStyleSheet("font-size: 14px; padding: 5px;")
                
                def update_pos_combo(index, pos_combo=combo_pos, l_combo=combo_loc, w_combo=combo_ws, p_lbl=lbl_pos):
                    pos_combo.clear()
                    loc_data = l_combo.currentData()
                    if not loc_data: return
                    if loc_data["type"] in ("furnace", "utir"):
                        p_lbl.show()
                        pos_combo.show()
                        ws_name = w_combo.currentText()
                        if "92" in ws_name:
                            tmpl = ["КСП-3", "Термопары"]
                        else:
                            tmpl = [
                                "Расход газа (КСД-2)", 
                                "Расход воздуха (КСД-2)", 
                                "Температура в печи (КСП-4)", 
                                "Температура гибких (аттестация) (КСП-4)", 
                                "Давление в печи (КСД-2)",
                                "Температура дыма и воздуха после рекуператора",
                                "Температура дыма до рекуператора"
                            ]
                        pos_combo.addItems(tmpl)
                    else:
                        p_lbl.hide()
                        pos_combo.hide()
                        pos_combo.addItem("")
                        
                def update_loc_combo(index, l_combo=combo_loc, w_combo=combo_ws, pc=combo_pos, pl=lbl_pos):
                    l_combo.clear()
                    ws_id = w_combo.currentData()
                    if not ws_id: return
                    ws_locs = [l for l in get_locations(ws_id) if l["type"] != "unassigned"]
                    for l in ws_locs:
                        l_combo.addItem(l["name"], l)
                    update_pos_combo(0, pc, l_combo, w_combo, pl)
                        
                combo_loc.currentIndexChanged.connect(
                    lambda idx, pc=combo_pos, lc=combo_loc, wc=combo_ws, pl=lbl_pos: update_pos_combo(idx, pc, lc, wc, pl)
                )
                
                combo_ws.currentIndexChanged.connect(
                    lambda idx, lc=combo_loc, wc=combo_ws, pc=combo_pos, pl=lbl_pos: update_loc_combo(idx, lc, wc, pc, pl)
                )
                
                for w_dict in workshops:
                    combo_ws.addItem(w_dict["name"], w_dict["id"])
                    
                origin_ws_idx = combo_ws.findData(d["ws_id"])
                if origin_ws_idx >= 0:
                    combo_ws.setCurrentIndex(origin_ws_idx)
                else:
                    if combo_ws.count() > 0:
                        update_loc_combo(0, combo_loc, combo_ws, combo_pos, lbl_pos)
                
                controls_lyt.addWidget(lbl_ws)
                controls_lyt.addWidget(combo_ws, 1)
                controls_lyt.addWidget(lbl_loc)
                controls_lyt.addWidget(combo_loc, 1)
                controls_lyt.addWidget(lbl_pos)
                controls_lyt.addWidget(combo_pos, 1)
                
                btn_assign = QPushButton("Назначить")
                btn_assign.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; font-size: 14px; padding: 5px 15px; border-radius: 4px;")
                btn_assign.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_assign.clicked.connect(
                    lambda checked, dev_id=d["id"], c_loc=combo_loc, c_pos=combo_pos: self.assign_unassigned_device(dev_id, c_loc, c_pos)
                )
                controls_lyt.addWidget(btn_assign)
                
                card_lyt.addLayout(controls_lyt)
                self.unassigned_layout.addWidget(card)
                
                update_pos_combo(0, combo_pos, combo_loc, combo_ws, lbl_pos)

        # Populate Tasks
        while self.tasks_layout.count():
            item = self.tasks_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
                
        tasks = get_devices_for_calibration(months_margin=3)
        
        if not tasks:
            lbl_empty = QLabel("✅ Нет приборов, требующих поверки в ближайшие 3 месяца!")
            lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_empty.setStyleSheet("font-size: 20px; font-weight: bold; color: #4CAF50; margin-top: 50px;")
            self.tasks_layout.addWidget(lbl_empty)
        else:
            lbl_info = QLabel("Приборы, у которых дата поверки наступает менее чем через 3 месяца:")
            lbl_info.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 10px;")
            self.tasks_layout.addWidget(lbl_info)
            
            for t in tasks:
                card = QFrame()
                card.setStyleSheet("QFrame { background: white; border-radius: 8px; border: 1px solid #ddd; padding: 10px; border-left: 5px solid #FF9800; }")
                card_lyt = QVBoxLayout(card)
                
                sn_str = t["serial_number"] if t["serial_number"] else "Нет"
                lbl_title = QLabel(f"<b>{t['name']}</b> (Зав. №: {sn_str})")
                lbl_title.setStyleSheet("font-size: 16px;")
                card_lyt.addWidget(lbl_title)
                
                loc_type = {"furnace": "Печь", "utir": "УТИР", "storage": "Кладовка", "general": "Место"}.get(t["location_type"], "Место")
                lbl_origin = QLabel(f"Цех: <b>{t['workshop_name']}</b> | Место: <b>{t['location_name']} ({loc_type})</b>")
                lbl_origin.setStyleSheet("font-size: 14px; color: #555;")
                card_lyt.addWidget(lbl_origin)
                
                cal_date_html = get_colored_date_html(t["calibration_date"])
                lbl_date = QLabel(f"Дата следующей поверки: {cal_date_html}")
                lbl_date.setStyleSheet("font-size: 15px; margin-top: 5px;")
                card_lyt.addWidget(lbl_date)
                
                controls_lyt = QHBoxLayout()
                controls_lyt.addStretch()
                
                btn_done = QPushButton("Отметить как замененный")
                btn_done.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; font-size: 14px; padding: 5px 15px; border-radius: 4px;")
                btn_done.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_done.clicked.connect(lambda checked, dev_id=t["id"]: self.mark_task_done(dev_id))
                controls_lyt.addWidget(btn_done)
                
                card_lyt.addLayout(controls_lyt)
                self.tasks_layout.addWidget(card)
            
    def mark_task_done(self, device_id):
        reply = QMessageBox.question(
            self, "Подтверждение",
            "Вы уверены, что прибор был заменен? Он будет перемещен в кладовку, а для текущего места нужно будет добавить новый прибор.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            logging.info(f"Marking task done (device replaced) for device_id: {device_id}")
            replace_device(device_id, to_storage=True)
            QMessageBox.information(self, "Успех", "Прибор перемещен в резерв (кладовку).")
            self.refresh_db()
 
    def assign_unassigned_device(self, device_id, combo_loc, combo_pos):
        loc_data = combo_loc.currentData()
        if not loc_data: return
        pos = combo_pos.currentText()
        logging.info(f"Assigning unassigned device: {device_id} to location: {loc_data['name']} (pos: {pos})")
        update_device_location(device_id, loc_data["id"], pos)
        QMessageBox.information(self, "Успех", "Прибор успешно распределен!")
        self.refresh_db()
 
    def unassign_device(self, device_id, ws_id):
        unassigned_loc_id = get_unassigned_location(ws_id)
        logging.info(f"Unassigning device: {device_id} in workshop_id: {ws_id}")
        update_device_location(device_id, unassigned_loc_id, None)
        QMessageBox.information(self, "Успех", "Прибор перемещен в 'Требуют распределения'.")
        self.refresh_db()
 
    def upload_file(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Выберите документ или фото сертификата", "",
            "Все поддерживаемые (*.xlsx *.xls *.docx *.pdf *.txt *.csv *.jpg *.jpeg *.png *.bmp *.tiff *.webp);;"
            "Excel (*.xlsx *.xls);;"
            "Документы (*.docx *.pdf *.txt *.csv);;"
            "Изображения (*.jpg *.jpeg *.png *.bmp *.tiff *.webp);;"
            "Все файлы (*)"
        )
        if filepath:
            logging.info(f"Uploading file: {filepath}")
            self.btn_upload.setEnabled(False)
            ext = os.path.splitext(filepath)[1].lower()
            if ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'):
                self.lbl_upload_status.setText("Распознавание фото через ИИ... Пожалуйста, подождите.")
            elif ext in ('.xlsx', '.xls'):
                self.lbl_upload_status.setText("Обработка Excel-файла... Пожалуйста, подождите.")
            else:
                self.lbl_upload_status.setText("Обработка документа через ИИ... Пожалуйста, подождите.")
            
            comment = self.upload_comment.text().strip()
            self.worker = IngestWorker(filepath, comment)
            self.worker.finished.connect(self.on_upload_finished)
            self.worker.start()
            
    def on_upload_finished(self, success, msg):
        self.btn_upload.setEnabled(True)
        if success:
            logging.info("File upload and parsing finished successfully.")
            self.lbl_upload_status.setText("Успешно!")
            QMessageBox.information(self, "Результат", msg)
            self.refresh_db()
        else:
            logging.error(f"File upload/parsing failed: {msg}")
            self.lbl_upload_status.setText("Ошибка.")
            QMessageBox.critical(self, "Ошибка", msg)
 
    def edit_workshop_scheme(self):
        current_idx = self.workshop_tabs.currentIndex()
        if current_idx < 0:
            QMessageBox.warning(self, "Внимание", "Нет выбранного цеха.")
            return
            
        scroll = self.workshop_tabs.widget(current_idx)
        if not scroll:
            return
            
        ws_id = scroll.property("ws_id")
        ws_name = scroll.property("ws_name")
        
        if not ws_id:
            QMessageBox.warning(self, "Ошибка", "Не удалось определить цех.")
            return

        # Activate edit mode on the embedded SchemeEditorWidget on the tab
        scheme_widget = scroll.findChild(SchemeEditorWidget)
        if scheme_widget:
            scheme_widget.toggle_edit_mode(True)
        
        logging.info(f"Opening scheme location dialog for workshop: {ws_name}")
        dlg = WorkshopSchemeDialog(ws_id, ws_name, self)
        if dlg.exec():
            self.refresh_db()
