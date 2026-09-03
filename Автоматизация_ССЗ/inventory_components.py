import os
import difflib
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QDialog, QListWidget, QListWidgetItem, QScrollArea,
    QFrame, QGridLayout, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from inventory_db import (
    update_device_location, get_locations, add_location, delete_location
)


# ═══════════════════════════════════════════════════════════════════════════
#  Helper functions
# ═══════════════════════════════════════════════════════════════════════════

def format_date_ru(date_str):
    if not date_str:
        return "неизвестно"
    try:
        if "T" in date_str:
            date_str = date_str.split("T")[0]
        parts = date_str.split("-")
        if len(parts) == 3:
            return f"{parts[2]}.{parts[1]}.{parts[0]}"
    except Exception:
        pass
    return date_str


def get_colored_date_html(date_str):
    if not date_str:
        return "<span style='color: #999;'>неизвестно</span>"
    
    try:
        clean_date_str = date_str.split("T")[0] if "T" in date_str else date_str
        cal_date = datetime.strptime(clean_date_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        days_diff = (cal_date - today).days
        
        if days_diff < 0:
            color = "#D32F2F" # Red
        elif days_diff <= 90:
            color = "#F57C00" # Orange
        else:
            color = "#388E3C" # Green
            
        parts = clean_date_str.split("-")
        ru_date = f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else clean_date_str
        
        return f"<span style='color: {color}; font-weight: bold;'>{ru_date}</span>"
    except Exception:
        pass
    return f"<span>{date_str}</span>"


# ═══════════════════════════════════════════════════════════════════════════
#  Components & Dialogs
# ═══════════════════════════════════════════════════════════════════════════

class SmartDeviceSelector(QComboBox):
    def __init__(self, available_devices, location_id, position, parent_dashboard):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.available_devices = available_devices
        self.location_id = location_id
        self.position = position
        self.parent_dashboard = parent_dashboard
        
        self.lineEdit().setPlaceholderText("🔴 ПУСТО. Поиск (умный)...")
        self.setStyleSheet("font-size: 13px; padding: 2px; border: 1px solid #ff9800; border-radius: 4px;")
        
        self.lineEdit().textEdited.connect(self.on_text_edited)
        self.activated.connect(self.on_activated)
        
    def showPopup(self):
        if self.count() == 0:
            self.populate_all()
        super().showPopup()
        
    def populate_all(self):
        self.clear()
        self.addItem("", None)
        count = 0
        for d in self.available_devices:
            ws_hint = "Резерв" if d['location_type'] == 'storage' else ("Нераспределенные" if d['location_type'] == 'unassigned' else d['workshop_name'])
            text = f"{d['name']} (№ {d['serial_number'] or 'нет'}) - {ws_hint}"
            self.addItem(text, d['id'])
            count += 1
            if count >= 30:
                break
            
    def on_text_edited(self, text):
        query = text.strip().lower().replace('\t', ' ')
        self.clear()
        self.addItem("", None)
        
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
            cal = str(d['calibration_date'] or '').lower()
            target = f"{d['name'].lower()} {sn} {cal} {d['workshop_name'].lower()}"
            if not query or smart_match(query, target):
                ws_hint = "Резерв" if d['location_type'] == 'storage' else ("Нераспределенные" if d['location_type'] == 'unassigned' else d['workshop_name'])
                self.addItem(f"{d['name']} (№ {d['serial_number'] or 'нет'}) - {ws_hint}", d['id'])
                count += 1
            if count >= 30:
                break
                
        self.lineEdit().setText(text)
        if count > 0 and text:
            self.showPopup()
        
    def on_activated(self, index):
        dev_id = self.itemData(index)
        if dev_id:
            update_device_location(dev_id, self.location_id, self.position)
            self.parent_dashboard.refresh_db()


class FurnaceSchemaDialog(QDialog):
    def __init__(self, ws_name, loc_name, template, devices, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Схема печи: {loc_name} ({ws_name})")
        self.resize(700, 550)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        lbl_title = QLabel(f"🔥 {loc_name} ({ws_name})")
        lbl_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #2C3E50;")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)
        
        lbl_desc = QLabel("Список мест установки приборов и текущее оборудование")
        lbl_desc.setStyleSheet("font-size: 14px; color: #7F8C8D;")
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_desc)
        
        used_devices = set()
        template_installed = 0
        
        for slot in template:
            for d in devices:
                if d.get("position") == slot and d["id"] not in used_devices:
                    used_devices.add(d["id"])
                    template_installed += 1
                    break
                    
        extra_devs = [d for d in devices if d["id"] not in used_devices]
        total_installed = len(used_devices) + len(extra_devs)
        
        lbl_stats = QLabel(f"<b>Всего мест:</b> {len(template)} | <b>Установлено приборов:</b> {total_installed} (по шаблону: {template_installed}, доп: {len(extra_devs)})")
        lbl_stats.setStyleSheet("font-size: 13px; color: #34495E; background: #EBF5FB; padding: 6px 12px; border-radius: 6px; border: 1px solid #AED6F1;")
        lbl_stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_stats)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        main_vbox = QVBoxLayout(container)
        main_vbox.setSpacing(15)
        
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setSpacing(12)
        grid.setContentsMargins(0, 0, 0, 0)
        
        used_devices.clear()
        
        for i, slot in enumerate(template):
            device = None
            for d in devices:
                if d.get("position") == slot and d["id"] not in used_devices:
                    device = d
                    used_devices.add(d["id"])
                    break
            
            frame = QFrame()
            frame.setStyleSheet("""
                QFrame {
                    border: 1px solid #E0E0E0;
                    border-radius: 10px;
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #f8f9fa);
                }
            """)
            flayout = QVBoxLayout(frame)
            flayout.setContentsMargins(12, 12, 12, 12)
            flayout.setSpacing(6)
            
            lbl_slot = QLabel(f"<b>Позиция:</b> {slot}")
            lbl_slot.setWordWrap(True)
            lbl_slot.setStyleSheet("border: none; background: transparent; font-size: 14px; color: #34495E;")
            flayout.addWidget(lbl_slot)
            
            if device:
                sn = device['serial_number'] or 'нет'
                lbl_dev = QLabel(f"✅ Установлено: <b>{device['name']}</b> (Зав.№: {sn})")
                lbl_dev.setWordWrap(True)
                lbl_dev.setStyleSheet("border: none; background: transparent; color: #27AE60; font-size: 13px;")
                flayout.addWidget(lbl_dev)
                
                cal_date_html = get_colored_date_html(device['calibration_date'])
                lbl_cal = QLabel(f"Поверка до: {cal_date_html}")
                lbl_cal.setStyleSheet("border: none; background: transparent; font-size: 12px; color: #7F8C8D;")
                flayout.addWidget(lbl_cal)
            else:
                lbl_dev = QLabel("🔴 НЕ УСТАНОВЛЕНО")
                lbl_dev.setStyleSheet("border: none; background: transparent; color: #E74C3C; font-weight: bold; font-size: 13px;")
                flayout.addWidget(lbl_dev)
                
            row = i // 2
            col = i % 2
            grid.addWidget(frame, row, col)
            
        main_vbox.addWidget(grid_widget)
        
        if extra_devs:
            lbl_extra_hdr = QLabel("<b>Дополнительные приборы на этой печи:</b>")
            lbl_extra_hdr.setStyleSheet("font-size: 14px; color: #2C3E50; margin-top: 10px;")
            main_vbox.addWidget(lbl_extra_hdr)
            
            for ed in extra_devs:
                ed_frame = QFrame()
                ed_frame.setStyleSheet("QFrame { background: #FFFFFF; border: 1px solid #DDD; border-radius: 6px; padding: 8px; }")
                ed_lyt = QVBoxLayout(ed_frame)
                ed_lyt.setContentsMargins(10, 8, 10, 8)
                
                sn = ed["serial_number"] or "нет"
                pos_str = f" (Позиция: {ed['position']})" if ed.get('position') else ""
                lbl_ed = QLabel(f"• <b>{ed['name']}</b> (Зав.№: {sn}){pos_str}")
                lbl_ed.setStyleSheet("font-size: 13px; color: #2C3E50;")
                ed_lyt.addWidget(lbl_ed)
                
                cal_date_html = get_colored_date_html(ed['calibration_date'])
                lbl_ed_cal = QLabel(f"Поверка до: {cal_date_html}")
                lbl_ed_cal.setStyleSheet("font-size: 12px; color: #7F8C8D;")
                ed_lyt.addWidget(lbl_ed_cal)
                
                main_vbox.addWidget(ed_frame)
            
        scroll.setWidget(container)
        layout.addWidget(scroll)
        
        btn_close = QPushButton("Закрыть")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setFixedWidth(180)
        btn_close.setFixedHeight(38)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #3498DB; 
                color: white; 
                font-size: 14px; 
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #2980B9;
            }
        """)
        btn_close.clicked.connect(self.accept)
        
        h_layout = QHBoxLayout()
        h_layout.addStretch()
        h_layout.addWidget(btn_close)
        h_layout.addStretch()
        
        layout.addLayout(h_layout)


class WorkshopSchemeDialog(QDialog):
    def __init__(self, ws_id, ws_name, parent=None):
        super().__init__(parent)
        self.ws_id = ws_id
        self.ws_name = ws_name
        self.setWindowTitle(f"Редактирование схемы: {ws_name}")
        self.resize(500, 400)
        self.setup_ui()
        self.load_locations()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        self.list_locs = QListWidget()
        layout.addWidget(QLabel("Места в цехе:"))
        layout.addWidget(self.list_locs)
        
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("Добавить место")
        self.btn_add.setObjectName("btn_success")
        self.btn_add.clicked.connect(self.add_loc)
        
        self.btn_del = QPushButton("Удалить выбранное")
        self.btn_del.setObjectName("btn_danger")
        self.btn_del.clicked.connect(self.del_loc)
        
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_del)
        layout.addLayout(btn_layout)
        
        self.btn_close = QPushButton("Закрыть")
        self.btn_close.clicked.connect(self.accept)
        layout.addWidget(self.btn_close)
        
    def load_locations(self):
        self.list_locs.clear()
        locs = get_locations(self.ws_id)
        for loc in locs:
            item = QListWidgetItem(f"{loc['name']} ({'Печь' if loc['type'] == 'furnace' else 'УТИР' if loc['type'] == 'utir' else 'Кладовка'})")
            item.setData(Qt.ItemDataRole.UserRole, loc)
            self.list_locs.addItem(item)
            
    def add_loc(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Новое место", "Название:")
        if ok and name:
            items = ["Печь (furnace)", "УТИР (utir)", "Кладовка (storage)"]
            type_display, ok2 = QInputDialog.getItem(self, "Тип", "Выберите тип:", items, 0, False)
            if ok2 and type_display:
                if "furnace" in type_display: type_val = "furnace"
                elif "utir" in type_display: type_val = "utir"
                else: type_val = "storage"
                add_location(self.ws_id, name, type_val)
                self.load_locations()
                
    def del_loc(self):
        curr = self.list_locs.currentItem()
        if not curr: return
        loc = curr.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(self, "Удаление", f"Удалить место '{loc['name']}'? Все приборы на этом месте также будут удалены.")
        if reply == QMessageBox.StandardButton.Yes:
            delete_location(loc['id'])
            self.load_locations()
