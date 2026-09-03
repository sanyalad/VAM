import difflib
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QTabWidget, QWidget, QCheckBox, QLineEdit, QDateEdit, QTableWidget,
    QTableWidgetItem, QMessageBox, QHeaderView, QListWidget, QListWidgetItem,
    QGroupBox, QFormLayout, QScrollArea
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QFont, QColor

from checklist_db import (
    create_replacement_task, get_open_tasks, get_task_items,
    save_item_result, close_task, get_replacement_history, delete_task
)
from inventory_db import get_workshops, get_locations, get_devices, get_furnace_template
from checklist_printer import create_and_print_checklist
from ssz_config import CONFIG

class SmartDeviceSelector(QComboBox):
    def __init__(self, available_devices):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.available_devices = available_devices
        
        self.lineEdit().setPlaceholderText("🔴 Введите название или выберите из БД...")
        self.setStyleSheet("font-size: 13px; padding: 2px;")
        
        self.lineEdit().textEdited.connect(self.on_text_edited)
        
    def showPopup(self):
        if self.count() == 0:
            self.populate_all()
        super().showPopup()
        
    def populate_all(self):
        self.clear()
        self.addItem("", None)
        count = 0
        for d in self.available_devices:
            text = f"{d['name']} (№ {d['serial_number'] or 'нет'})"
            self.addItem(text, d)
            count += 1
            if count >= 30:
                break
            
    def on_text_edited(self, text):
        query = text.strip().lower().replace('\t', ' ')
        self.clear()
        self.addItem(text, None) # Allow custom text
        
        if not query:
            return
            
        def is_fuzzy_match(word, txt):
            if word in txt: return True
            if len(word) > 3:
                for t in txt.replace("-", " ").replace(".", " ").split():
                    if difflib.SequenceMatcher(None, word, t).ratio() > 0.75:
                        return True
            return False
            
        def smart_match(q, txt):
            for w in q.split():
                if not is_fuzzy_match(w, txt): return False
            return True
            
        count = 0
        for d in self.available_devices:
            sn = str(d['serial_number'] or '').lower()
            target = f"{d['name'].lower()} {sn}"
            if smart_match(query, target):
                self.addItem(f"{d['name']} (№ {d['serial_number'] or 'нет'})", d)
                count += 1
            if count >= 30:
                break
                
        self.lineEdit().setText(text)
        if count > 0 and text:
            self.showPopup()

class CloseTaskDialog(QDialog):
    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task = task
        self.setWindowTitle(f"Закрытие задания #{task['id']}")
        self.resize(800, 500)
        
        self.task_data = get_task_items(task['id'])
        self.available_devices = get_devices() # All devices for smart search
        
        layout = QVBoxLayout(self)
        
        info_lbl = QLabel(f"<b>Объект:</b> {task['workshop_name']} — {task['location_name']}<br>"
                          f"<b>Исполнитель:</b> {task['executor']}<br>"
                          f"<b>Создано:</b> {task['created_at']}")
        layout.addWidget(info_lbl)
        
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Позиция", "Снято", "Установлен (название или из БД)", "№ / Поверка"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setRowCount(len(self.task_data['items']))
        
        self.item_inputs = []
        
        for row, item in enumerate(self.task_data['items']):
            # Pos
            pos_item = QTableWidgetItem(item['position'])
            pos_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 0, pos_item)
            
            # Removed
            removed_text = "Пусто"
            if item['removed_device_id']:
                removed_text = f"{item['removed_name']}\n№ {item['removed_serial'] or 'нет'}"
            rem_item = QTableWidgetItem(removed_text)
            rem_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 1, rem_item)
            
            if item['status'] == 'done':
                inst_text = f"{item['installed_name']}\n№ {item['installed_serial']} до {item['installed_cal_date']}"
                inst_item = QTableWidgetItem(inst_text)
                inst_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(row, 2, inst_item)
                self.table.setItem(row, 3, QTableWidgetItem("Готово"))
                self.item_inputs.append(None)
            else:
                selector = SmartDeviceSelector(self.available_devices)
                self.table.setCellWidget(row, 2, selector)
                
                widget_container = QWidget()
                h_lay = QHBoxLayout(widget_container)
                h_lay.setContentsMargins(0,0,0,0)
                serial_edit = QLineEdit()
                serial_edit.setPlaceholderText("№")
                date_edit = QDateEdit(QDate.currentDate())
                date_edit.setCalendarPopup(True)
                date_edit.setDisplayFormat("yyyy-MM-dd")
                h_lay.addWidget(serial_edit)
                h_lay.addWidget(date_edit)
                
                self.table.setCellWidget(row, 3, widget_container)
                
                # Auto-fill serial and date when selecting from DB
                def on_select(idx, s_edit=serial_edit, d_edit=date_edit, sel=selector):
                    data = sel.itemData(idx)
                    if data:
                        s_edit.setText(data['serial_number'] or "")
                        if data['calibration_date']:
                            try:
                                d_edit.setDate(QDate.fromString(data['calibration_date'][:10], "yyyy-MM-dd"))
                            except:
                                pass
                selector.currentIndexChanged.connect(on_select)
                
                self.item_inputs.append({
                    "id": item['id'],
                    "selector": selector,
                    "serial": serial_edit,
                    "date": date_edit
                })
                
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        btn_close = QPushButton("Закрыть всё и обновить БД")
        btn_close.setObjectName("btn_success")
        btn_close.clicked.connect(self.on_accept)
        
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)
        
    def on_accept(self):
        for inputs in self.item_inputs:
            if not inputs: continue
            
            sel = inputs['selector']
            data = sel.itemData(sel.currentIndex())
            text = sel.currentText()
            
            if not text.strip():
                # skipped
                continue
                
            installed_device_id = data['id'] if data else None
            installed_name = data['name'] if data else text
            installed_serial = inputs['serial'].text()
            installed_cal_date = inputs['date'].date().toString("yyyy-MM-dd")
            
            save_item_result(inputs['id'], installed_device_id, installed_name, installed_serial, installed_cal_date)
            
        # Check if all done
        task_data = get_task_items(self.task['id'])
        all_done = True
        for item in task_data['items']:
            if item['status'] != 'done':
                all_done = False
                break
                
        if all_done:
            close_task(self.task['id'])
            QMessageBox.information(self, "Успех", "Задание закрыто, приборы обновлены в БД.")
            self.accept()
        else:
            QMessageBox.warning(self, "Частично", "Не все позиции заполнены. Задание остаётся открытым.")
            self.accept()

class ChecklistDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Задания на замену приборов")
        self.resize(800, 600)
        
        self.layout = QVBoxLayout(self)
        
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)
        
        self._init_create_tab()
        self._init_open_tab()
        self._init_history_tab()
        
    def _init_create_tab(self):
        self.tab_create = QWidget()
        layout = QVBoxLayout(self.tab_create)
        
        form_layout = QFormLayout()
        
        self.cb_executor = QComboBox()
        self.cb_executor.addItems([
            CONFIG.get("executor_1", "Наладчик КИПиА Таратов Д.В."),
            CONFIG.get("executor_2", "Наладчик КИПиА Гаврилов М.Ю."),
            "Наладчик КИПиА Войтов А.М.",
            "Наладчик КИПиА Дмитриев И.С."
        ])
        form_layout.addRow("Исполнитель:", self.cb_executor)
        
        self.cb_workshop = QComboBox()
        self.workshops = get_workshops()
        for w in self.workshops:
            self.cb_workshop.addItem(w['name'], w['id'])
        self.cb_workshop.currentIndexChanged.connect(self._on_workshop_changed)
        form_layout.addRow("Цех:", self.cb_workshop)
        
        self.cb_location = QComboBox()
        self.cb_location.currentIndexChanged.connect(self._on_location_changed)
        form_layout.addRow("Печь / Объект:", self.cb_location)
        
        self.le_note = QLineEdit()
        form_layout.addRow("Примечание:", self.le_note)
        
        layout.addLayout(form_layout)
        
        # Items selection
        self.group_items = QGroupBox("Позиции для замены")
        self.items_layout = QVBoxLayout(self.group_items)
        layout.addWidget(self.group_items)
        
        self.checkboxes = []
        self.current_devices = []
        
        btn_layout = QHBoxLayout()
        self.btn_create = QPushButton("Сформировать + Печать")
        self.btn_create.setObjectName("btn_primary")
        self.btn_create.clicked.connect(self._on_create)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_create)
        
        layout.addStretch()
        layout.addLayout(btn_layout)
        
        self.tabs.addTab(self.tab_create, "Создать задание")
        self._on_workshop_changed()
        
    def _on_workshop_changed(self):
        ws_id = self.cb_workshop.currentData()
        if not ws_id: return
        self.cb_location.clear()
        locs = get_locations(ws_id)
        for l in locs:
            if l['type'] in ('furnace', 'utir'):
                self.cb_location.addItem(l['name'], l['id'])
        
    def _on_location_changed(self):
        # Clear old checkboxes
        for chk, _ in self.checkboxes:
            self.items_layout.removeWidget(chk)
            chk.deleteLater()
        self.checkboxes.clear()
        
        loc_id = self.cb_location.currentData()
        if not loc_id: return
        
        ws_name = self.cb_workshop.currentText()
        template = get_furnace_template(ws_name)
        self.current_devices = get_devices(loc_id)
        
        for pos in template:
            dev = next((d for d in self.current_devices if d['position'] == pos), None)
            dev_text = f"{dev['name']} (№ {dev['serial_number'] or 'нет'})" if dev else "Пусто"
            chk = QCheckBox(f"{pos}  |  Сейчас: {dev_text}")
            chk.setChecked(True)
            self.items_layout.addWidget(chk)
            self.checkboxes.append((chk, pos))

    def _on_create(self):
        executor = self.cb_executor.currentText()
        ws_id = self.cb_workshop.currentData()
        ws_name = self.cb_workshop.currentText()
        loc_id = self.cb_location.currentData()
        loc_name = self.cb_location.currentText()
        note = self.le_note.text()
        
        items_data = []
        for chk, pos in self.checkboxes:
            if chk.isChecked():
                dev = next((d for d in self.current_devices if d['position'] == pos), None)
                items_data.append({
                    'position': pos,
                    'removed_device_id': dev['id'] if dev else None
                })
                
        if not items_data:
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы одну позицию.")
            return
            
        task_id = create_replacement_task(executor, ws_id, loc_id, items_data, note)
        
        # Print
        create_and_print_checklist(task_id, executor, ws_name, loc_name, note)
        
        QMessageBox.information(self, "Успех", f"Задание #{task_id} создано и отправлено на печать.")
        self._refresh_open_tab()
        self.tabs.setCurrentIndex(1)

    def _init_open_tab(self):
        self.tab_open = QWidget()
        layout = QVBoxLayout(self.tab_open)
        
        self.list_open = QListWidget()
        self.list_open.itemDoubleClicked.connect(self._on_open_task_dblclick)
        layout.addWidget(self.list_open)
        
        btn_layout = QHBoxLayout()
        btn_del = QPushButton("Удалить задание")
        btn_del.setObjectName("btn_danger")
        btn_del.clicked.connect(self._on_delete_task)
        
        btn_close = QPushButton("Заполнить / Закрыть")
        btn_close.setObjectName("btn_success")
        btn_close.clicked.connect(lambda: self._on_open_task_dblclick(self.list_open.currentItem()))
        
        btn_layout.addWidget(btn_del)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        
        layout.addLayout(btn_layout)
        self.tabs.addTab(self.tab_open, "Открытые задания")
        self._refresh_open_tab()
        
    def _refresh_open_tab(self):
        self.list_open.clear()
        tasks = get_open_tasks()
        for t in tasks:
            item = QListWidgetItem(f"#{t['id']} | {t['workshop_name']} - {t['location_name']} | Исполнитель: {t['executor']} | Выполнено: {t['items_done']}/{t['items_count']}")
            item.setData(Qt.ItemDataRole.UserRole, t)
            self.list_open.addItem(item)
            
    def _on_open_task_dblclick(self, item):
        if not item: return
        task = item.data(Qt.ItemDataRole.UserRole)
        dlg = CloseTaskDialog(task, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh_open_tab()
            self._refresh_history_tab()

    def _on_delete_task(self):
        item = self.list_open.currentItem()
        if not item: return
        task = item.data(Qt.ItemDataRole.UserRole)
        
        ans = QMessageBox.question(self, "Удаление", f"Точно удалить задание #{task['id']}?\nОно не будет завершено.")
        if ans == QMessageBox.StandardButton.Yes:
            delete_task(task['id'])
            self._refresh_open_tab()

    def _init_history_tab(self):
        self.tab_history = QWidget()
        layout = QVBoxLayout(self.tab_history)
        
        self.table_history = QTableWidget()
        self.table_history.setColumnCount(4)
        self.table_history.setHorizontalHeaderLabels(["Дата / Исполнитель", "Объект", "Позиция", "Замена"])
        self.table_history.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table_history)
        
        self.tabs.addTab(self.tab_history, "История")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        
    def _on_tab_changed(self, idx):
        if idx == 1:
            self._refresh_open_tab()
        elif idx == 2:
            self._refresh_history_tab()
            
    def _refresh_history_tab(self):
        history = get_replacement_history()
        self.table_history.setRowCount(0)
        
        row = 0
        for task in history:
            for item in task['items']:
                self.table_history.insertRow(row)
                
                self.table_history.setItem(row, 0, QTableWidgetItem(f"{task['created_at'][:10]}\n{task['executor']}"))
                self.table_history.setItem(row, 1, QTableWidgetItem(f"{task['workshop_name']}\n{task['location_name']}"))
                self.table_history.setItem(row, 2, QTableWidgetItem(item['position']))
                self.table_history.setItem(row, 3, QTableWidgetItem(f"Снято: {item['removed']}\nУстановлено: {item['installed']}"))
                self.table_history.setRowHeight(row, 60)
                row += 1
