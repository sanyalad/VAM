import os
import json
import requests
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTextEdit
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

NOTES_FILE = "заметки.txt"

# Сюда нужно будет вставить URL развернутого Web App из Google Apps Script
# Пример: "https://script.google.com/macros/s/AKfycby.../exec"
GAS_WEB_APP_URL = "" 

def fetch_notes_from_cloud():
    """Получает заметки из Google Apps Script."""
    if not GAS_WEB_APP_URL:
        return None
        
    try:
        response = requests.get(GAS_WEB_APP_URL, params={"action": "get_notes"}, timeout=2.0)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None

def has_notes():
    """Проверяет, есть ли заметки в облаке или локальном файле."""
    # Сначала проверяем облако
    cloud_notes = fetch_notes_from_cloud()
    if cloud_notes and isinstance(cloud_notes, list) and len(cloud_notes) > 0:
        if "error" not in cloud_notes[0]:
            return True
            
    # Фолбэк на локальный файл
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, NOTES_FILE)
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                return len(content) > 0
        except Exception:
            pass
            
    return False

class NotesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("План / Заметки")
        self.setFixedSize(650, 500)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)
        
        lbl_title = QLabel("План на сегодня:")
        lbl_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #D32F2F;")
        layout.addWidget(lbl_title)
        
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Segoe UI", 11))
        self.text_edit.setStyleSheet("background-color: #FFF3E0; border: 1px solid #FFCC80; border-radius: 4px; padding: 10px; color: #333333;")
        layout.addWidget(self.text_edit)
        
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("Ознакомлен")
        btn_ok.setObjectName("btn_primary")
        btn_ok.setFixedSize(150, 40)
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.clicked.connect(self.accept)
        
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
        self._load_notes()

    def _load_notes(self):
        # 1. Пробуем загрузить из облака
        cloud_notes = fetch_notes_from_cloud()
        if cloud_notes and isinstance(cloud_notes, list) and len(cloud_notes) > 0:
            if "error" not in cloud_notes[0]:
                text = ""
                for note in cloud_notes:
                    text += f"📅 {note.get('date', '')}\n"
                    text += f"{note.get('text', '')}\n"
                    file_url = note.get('fileUrl', '')
                    if file_url:
                        text += f"📎 Документ: {file_url}\n"
                    text += "-" * 40 + "\n\n"
                
                self.text_edit.setPlainText(text.strip())
                return
                
        # 2. Фолбэк на локальный файл
        base_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(base_dir, NOTES_FILE)
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    self.text_edit.setPlainText(content)
            except Exception as e:
                self.text_edit.setPlainText(f"Ошибка чтения файла: {e}")

