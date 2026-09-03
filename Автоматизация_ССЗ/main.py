import os
import sys

# Перехват запуска в качестве фонового COM-воркера
if len(sys.argv) >= 4 and sys.argv[1] == "--excel-worker":
    import excel_worker
    excel_worker.main()
    sys.exit(0)

from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QFrame, QGridLayout, QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import Qt, QDate, QTimer, QPropertyAnimation, QEasingCurve, QPoint
from PyQt6.QtGui import QFont, QIcon, QColor, QKeySequence, QShortcut

from ssz_window import SszWindow, AdminSettingsDialog
from ssz_utils import get_executor
from ssz_config import CONFIG, save_config
from exam_trainer import ExamHubWidget, ExamSessionWidget
from autorun_utils import setup_autorun
from notes_dialog import has_notes, NotesDialog
from ppr_dashboard import PprDashboardWidget
from inventory_dashboard import InventoryDashboardWidget

PAGE_LOGIN = 0
PAGE_HUB = 1
PAGE_SSZ = 2
PAGE_EXAM_HUB = 3
PAGE_EXAM_SESSION = 4
PAGE_PPR_DASHBOARD = 5
PAGE_INVENTORY = 6

APP_VERSION = "2.3.0"

# Styles are loaded from style.qss



class LoginWidget(QWidget):
    def __init__(self, on_login, parent=None):
        super().__init__(parent)
        self.on_login = on_login
        
        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        from PyQt6.QtWidgets import QFrame, QGraphicsDropShadowEffect
        from PyQt6.QtGui import QColor
        
        self.card = QFrame()
        self.card.setObjectName("login_card")
        self.card.setStyleSheet("""
            QFrame#login_card {
                background-color: white;
                border-radius: 16px;
                border: 1px solid #E5E9F0;
            }
        """)
        self.card.setFixedSize(400, 380)
        
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 20))
        shadow.setOffset(0, 10)
        self.card.setGraphicsEffect(shadow)
        
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(40, 40, 40, 40)
        card_layout.setSpacing(20)
        
        self.lbl_icon = QLabel("👋")
        self.lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_icon.setStyleSheet("font-size: 48px; background: transparent;")
        card_layout.addWidget(self.lbl_icon)
        
        self.lbl_greeting = QLabel("")
        self.lbl_greeting.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_greeting.setMinimumHeight(70)
        self.lbl_greeting.setStyleSheet("font-size: 24px; font-weight: bold; color: #2B2D42; background: transparent; padding-bottom: 5px;")
        card_layout.addWidget(self.lbl_greeting)
        
        self.lbl_subtitle = QLabel("Для продолжения работы нажмите «Войти»")
        self.lbl_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_subtitle.setStyleSheet("font-size: 14px; color: #8D99AE; background: transparent;")
        card_layout.addWidget(self.lbl_subtitle)
        
        card_layout.addStretch()
        
        self.btn_login = QPushButton("Войти")
        self.btn_login.setFixedHeight(50)
        self.btn_login.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_login.setStyleSheet("""
            QPushButton {
                background-color: #4C6EF5;
                color: white;
                font-size: 16px;
                font-weight: bold;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background-color: #3B5BDB;
            }
            QPushButton:pressed {
                background-color: #364FC7;
            }
        """)
        self.btn_login.clicked.connect(self._handle_login)
        card_layout.addWidget(self.btn_login)
        
        self.btn_secondary = QPushButton("Зайти как Сменный")
        self.btn_secondary.setFixedHeight(50)
        self.btn_secondary.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_secondary.setStyleSheet("""
            QPushButton {
                background-color: #F8F9FA;
                color: #495057;
                font-size: 15px;
                font-weight: 600;
                border-radius: 8px;
                border: 1px solid #CED4DA;
            }
            QPushButton:hover {
                background-color: #E9ECEF;
            }
            QPushButton:pressed {
                background-color: #DEE2E6;
            }
        """)
        self.btn_secondary.clicked.connect(lambda: self._do_login("shift"))
        self.btn_secondary.hide()
        card_layout.addWidget(self.btn_secondary)
        
        card_layout.addSpacing(10)
        
        self.btn_change_user = QPushButton("Это не я? Выбрать другого")
        self.btn_change_user.setStyleSheet("""
            QPushButton {
                color: #868E96; 
                background: transparent; 
                border: none; 
                font-size: 14px;
            }
            QPushButton:hover {
                color: #4C6EF5;
                text-decoration: underline;
            }
        """)
        self.btn_change_user.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_change_user.clicked.connect(self._change_user)
        card_layout.addWidget(self.btn_change_user, alignment=Qt.AlignmentFlag.AlignCenter)
        
        main_layout.addWidget(self.card)
        
        self.current_role = "shift"
        self._init_login()

    @property
    def role(self):
        return getattr(self, "current_role", "shift")

    def _handle_login(self):
        self._do_login(self.current_role)

    def _change_user(self):
        from PyQt6.QtWidgets import QInputDialog
        executors = [
            "Александр Максимович (Войтов)", 
            "Михаил Юрьевич (Гаврилов)", 
            "Денис Владимирович (Таратов)",
            "Иван Сергеевич (Дмитриев)"
        ]
        item, ok = QInputDialog.getItem(self, "Кто на смене?", "Выберите себя:", executors, 0, False)
        if ok and item:
            name_map = {
                "Александр Максимович (Войтов)": "Наладчик КИПиА Войтов А.М.",
                "Михаил Юрьевич (Гаврилов)": "Наладчик КИПиА Гаврилов М.Ю.",
                "Денис Владимирович (Таратов)": "Наладчик КИПиА Таратов Д.В.",
                "Иван Сергеевич (Дмитриев)": "Наладчик КИПиА Дмитриев И.С."
            }
            real_name = name_map.get(item, item)
            CONFIG["session_user"] = real_name
            save_config(CONFIG)
            self._init_login()

    def _init_login(self):
        now = datetime.now()
        h = now.hour
        if 6 <= h < 12:
            greeting = "Доброе утро"
        elif 12 <= h < 18:
            greeting = "Добрый день"
        elif 18 <= h < 24:
            greeting = "Добрый вечер"
        else:
            greeting = "Доброй ночи"
            
        is_weekend = now.weekday() >= 5
        
        session_user = CONFIG.get("session_user")
        if session_user:
            executor = session_user
        else:
            executor = get_executor(now)
            
        is_voytov = "войтов" in executor.lower()
        if is_voytov:
            name_str = "Александр Максимович"
        elif "гаврилов" in executor.lower():
            name_str = "Михаил Юрьевич"
        elif "таратов" in executor.lower():
            name_str = "Денис Владимирович"
        elif "дмитриев" in executor.lower():
            name_str = "Иван Сергеевич"
        else:
            words = executor.split()
            name_str = " ".join(words[-2:]) if len(words) >= 2 else executor
            
        self.lbl_greeting.setText(f"{greeting},\n{name_str}!")
        
        if is_weekend:
            self.current_role = "admin" if is_voytov else "shift"
            self.btn_login.setText("Войти")
            self.btn_secondary.hide()
            self.card.setFixedSize(400, 380)
        else:
            if is_voytov:
                self.current_role = "admin"
                self.btn_login.setText("Войти как Админ")
                self.btn_secondary.show()
                self.card.setFixedSize(400, 440)
            else:
                self.current_role = "shift"
                self.btn_login.setText(f"Войти")
                self.btn_secondary.hide()
                self.card.setFixedSize(400, 380)
                
    def _do_login(self, role):
        self.on_login(role)

    def _animate_in(self):
        """Анимация появления карточки."""
        effect = self.card.graphicsEffect()
        self._fade_anim = QPropertyAnimation(self.card, b"pos")
        self._fade_anim.setDuration(280)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        start_pos = self.card.pos() + QPoint(0, 18)
        self._fade_anim.setStartValue(start_pos)
        self._fade_anim.setEndValue(self.card.pos())
        self._fade_anim.start()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(50, self._animate_in)

class HubWidget(QWidget):
    """Главный экран — сетка карточек 2×2."""

    def __init__(self, on_ssz, on_exam, on_ppr, on_inventory, parent=None):
        super().__init__(parent)
        self.role = "admin"
        self._on_ssz = on_ssz
        self._on_exam = on_exam
        self._on_ppr = on_ppr
        self._on_inventory = on_inventory

        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Шапка ──
        header = QFrame()
        header.setStyleSheet(
            "QFrame { background: qlineargradient("
            "x1:0, y1:0, x2:1, y2:0,"
            "stop:0 #2C3E50, stop:1 #3B5BDB); "
            "border-bottom: 2px solid #364FC7; }"
        )
        header.setFixedHeight(80)
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(28, 0, 28, 0)

        lbl_logo = QLabel("🔧")
        lbl_logo.setStyleSheet("font-size: 28px; background: transparent;")
        hdr_layout.addWidget(lbl_logo)

        hdr_text = QVBoxLayout()
        lbl_title = QLabel("ВАМ — Лаборатория ТО КИПиА")
        lbl_title.setStyleSheet(
            "font-size: 16px; font-weight: 700; color: #FFFFFF; "
            "background: transparent; letter-spacing: 0.3px;"
        )
        lbl_subtitle = QLabel("Рабочие инструменты")
        lbl_subtitle.setStyleSheet(
            "font-size: 11px; color: rgba(255,255,255,0.65); background: transparent;"
        )
        hdr_text.addWidget(lbl_title)
        hdr_text.addWidget(lbl_subtitle)
        hdr_layout.addLayout(hdr_text)
        hdr_layout.addStretch()

        today = QDate.currentDate()
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        month_names = ["янв", "фев", "мар", "апр", "май", "июн",
                       "июл", "авг", "сен", "окт", "ноя", "дек"]
        day_abbr = day_names[today.dayOfWeek() - 1]
        is_weekend = today.dayOfWeek() >= 6
        date_color = "#FFA94D" if is_weekend else "rgba(255,255,255,0.85)"
        lbl_date = QLabel(
            f"{day_abbr} {today.day()} {month_names[today.month()-1]}"
        )
        lbl_date.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {date_color}; "
            "background: transparent;"
        )
        hdr_layout.addWidget(lbl_date)
        root.addWidget(header)

        # ── Горячие клавиши ──
        # (устанавливаются снаружи из MainWindow)

        # ── Сетка карточек ──
        body = QWidget()
        body.setStyleSheet("background-color: #F0F2F5;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(28, 28, 28, 20)
        body_layout.setSpacing(0)

        grid = QGridLayout()
        grid.setSpacing(16)

        self._cards_data = [
            dict(
                id="ssz", icon="📋", title="ССЗ",
                desc="Сменно-суточные задания КИПиА",
                hint="Генерация и печать заданий на основе графиков ППР",
                color_top="#3B5BDB", color_bar="#4C6EF5",
                shortcut="Ctrl+1", on_click=on_ssz, admin_only=False,
            ),
            dict(
                id="exam", icon="⚡", title="Электробезопасность",
                desc="Тесты III группы и билеты ПТБ",
                hint="Подготовка к экзамену по электробезопасности",
                color_top="#2B8A3E", color_bar="#37B24D",
                shortcut="Ctrl+2", on_click=on_exam, admin_only=False,
            ),
            dict(
                id="ppr", icon="🔧", title="ППР",
                desc="Учет и сводка технических обслуживаний",
                hint="Просмотр, выполнение и печать графиков ППР",
                color_top="#E67700", color_bar="#F59F00",
                shortcut="Ctrl+3", on_click=on_ppr, admin_only=False,
            ),
            dict(
                id="inventory", icon="📊", title="Учет приборов",
                desc="Поверка и база данных КИП",
                hint="База данных приборов, задания на замену",
                color_top="#1971C2", color_bar="#339AF0",
                shortcut="Ctrl+4", on_click=on_inventory, admin_only=False,
            ),
        ]

        self._card_frames = {}
        for idx, cdata in enumerate(self._cards_data):
            row, col = divmod(idx, 2)
            card = self._make_card(cdata)
            self._card_frames[cdata["id"]] = card
            grid.addWidget(card, row, col)

        body_layout.addLayout(grid)
        body_layout.addStretch()

        # ── Нижняя строка: кнопка настроек + версия ──
        bottom = QHBoxLayout()
        self.btn_settings = QPushButton("⚙  Настройки (Администратор)")
        self.btn_settings.setObjectName("btn_secondary")
        self.btn_settings.setFixedHeight(38)
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.clicked.connect(self._show_settings)
        self.btn_settings.hide()
        bottom.addWidget(self.btn_settings)
        bottom.addStretch()
        lbl_version = QLabel(f"v{APP_VERSION}")
        lbl_version.setStyleSheet("font-size: 10px; color: #ADB5BD;")
        bottom.addWidget(lbl_version)
        body_layout.addLayout(bottom)

        root.addWidget(body, stretch=1)

    def _make_card(self, cdata: dict) -> QFrame:
        """Строит одну карточку навигации."""
        card = QFrame()
        card.setObjectName("hub_card")
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setMinimumHeight(180)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(18)
        shadow.setColor(QColor(0, 0, 0, 18))
        shadow.setOffset(0, 4)
        card.setGraphicsEffect(shadow)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Цветная полоса сверху
        top_bar = QFrame()
        top_bar.setFixedHeight(6)
        top_bar.setStyleSheet(
            f"background-color: {cdata['color_bar']}; "
            "border-top-left-radius: 11px; border-top-right-radius: 11px; border: none;"
        )
        layout.addWidget(top_bar)

        # Тело карточки
        body_frame = QFrame()
        body_frame.setStyleSheet(
            "QFrame { background: #FFFFFF; border-bottom-left-radius: 11px; "
            "border-bottom-right-radius: 11px; border: none; }"
        )
        body_layout = QVBoxLayout(body_frame)
        body_layout.setContentsMargins(20, 16, 20, 18)
        body_layout.setSpacing(8)

        # Иконка + заголовок
        top_row = QHBoxLayout()
        lbl_icon = QLabel(cdata["icon"])
        lbl_icon.setStyleSheet(
            "font-size: 30px; background: transparent;"
        )
        top_row.addWidget(lbl_icon)
        top_row.addStretch()

        # Бейдж горячей клавиши
        lbl_sc = QLabel(cdata["shortcut"])
        lbl_sc.setStyleSheet(
            "background-color: #F1F3F5; color: #868E96; border-radius: 4px; "
            "padding: 2px 7px; font-size: 9pt; font-weight: 600;"
        )
        top_row.addWidget(lbl_sc)
        body_layout.addLayout(top_row)

        # Заголовок карточки
        lbl_title = QLabel(cdata["title"])
        lbl_title.setStyleSheet(
            f"font-size: 15pt; font-weight: 700; color: {cdata['color_top']}; "
            "background: transparent;"
        )
        body_layout.addWidget(lbl_title)

        # Описание
        lbl_desc = QLabel(cdata["desc"])
        lbl_desc.setStyleSheet(
            "font-size: 10pt; color: #495057; background: transparent;"
        )
        lbl_desc.setWordWrap(True)
        body_layout.addWidget(lbl_desc)

        body_layout.addStretch()

        # Подсказка внизу
        lbl_hint = QLabel(cdata["hint"])
        lbl_hint.setStyleSheet(
            "font-size: 9pt; color: #ADB5BD; background: transparent;"
        )
        lbl_hint.setWordWrap(True)
        body_layout.addWidget(lbl_hint)

        layout.addWidget(body_frame, stretch=1)

        # Клик по всей карточке
        card.mousePressEvent = lambda _ev, fn=cdata["on_click"]: fn()
        return card

    def set_role(self, role):
        self.role = role
        if role == "admin":
            self.btn_settings.show()
        else:
            self.btn_settings.hide()

    def _show_settings(self):
        dlg = AdminSettingsDialog(self)
        dlg.exec()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ВАМ — Рабочие инструменты")
        self.resize(960, 880)

        font = QFont("Segoe UI", 10)
        self.setFont(font)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.login_widget = LoginWidget(self._on_login)
        self.hub = HubWidget(self._show_ssz, self._show_exam_hub, self._show_ppr_dashboard, self._show_inventory)
        self.ssz = SszWindow()
        self.exam_hub = ExamHubWidget()
        self.exam_session = ExamSessionWidget()
        self.ppr_dashboard = PprDashboardWidget()
        self.inventory_dashboard = InventoryDashboardWidget()

        self.stack.addWidget(self.login_widget)
        self.stack.addWidget(self.hub)
        self.stack.addWidget(self.ssz)
        self.stack.addWidget(self.exam_hub)
        self.stack.addWidget(self.exam_session)
        self.stack.addWidget(self.ppr_dashboard)
        self.stack.addWidget(self.inventory_dashboard)

        self.ssz.go_home.connect(self._show_hub)
        self.exam_hub.go_home.connect(self._show_hub)
        self.exam_hub.start_session.connect(self._start_exam)
        self.exam_session.back_to_hub.connect(self._show_exam_hub)
        self.ppr_dashboard.go_home.connect(self._show_hub)
        self.inventory_dashboard.go_home.connect(self._show_hub)

        # ── Горячие клавиши ──
        QShortcut(QKeySequence("Ctrl+1"), self).activated.connect(self._show_ssz)
        QShortcut(QKeySequence("Ctrl+2"), self).activated.connect(self._show_exam_hub)
        QShortcut(QKeySequence("Ctrl+3"), self).activated.connect(self._show_ppr_dashboard)
        QShortcut(QKeySequence("Ctrl+4"), self).activated.connect(self._show_inventory)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._on_escape)

    def closeEvent(self, event):
        self.ssz.closeEvent(event)
        if event.isAccepted():
            super().closeEvent(event)

    def _on_escape(self):
        """Escape — возврат на Hub с любого экрана (кроме логина)."""
        current = self.stack.currentIndex()
        if current not in (PAGE_LOGIN, PAGE_HUB):
            self._show_hub()

    def _on_login(self, role):
        self.hub.set_role(role)
        if hasattr(self.ssz, 'set_role'):
            self.ssz.set_role(role)
        if hasattr(self.inventory_dashboard, 'set_role'):
            self.inventory_dashboard.set_role(role)
        self.stack.setCurrentIndex(PAGE_HUB)
        
        # Показать указания начальника, если они есть
        if has_notes():
            try:
                dlg = NotesDialog(self)
                dlg.exec()
            except Exception:
                pass

    def _show_hub(self):
        self.stack.setCurrentIndex(PAGE_HUB)
        role = getattr(self.login_widget, "role", "admin")
        if hasattr(self.hub, "set_role"):
            self.hub.set_role(role)
        if hasattr(self.inventory_dashboard, "set_role"):
            self.inventory_dashboard.set_role(role)

    def _show_ssz(self):
        self.stack.setCurrentIndex(PAGE_SSZ)

    def _show_exam_hub(self):
        self.stack.setCurrentIndex(PAGE_EXAM_HUB)
        
    def _show_ppr_dashboard(self):
        self.stack.setCurrentIndex(PAGE_PPR_DASHBOARD)

    def _show_inventory(self):
        self.stack.setCurrentIndex(PAGE_INVENTORY)

    def _start_exam(self, module_id, mode, ticket_id):
        self.exam_session.start(module_id, mode, ticket_id)
        self.stack.setCurrentIndex(PAGE_EXAM_SESSION)


def main():
    import traceback
    import threading
    import logging
    from logging.handlers import RotatingFileHandler

    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Логи")
    os.makedirs(log_dir, exist_ok=True)
    crash_log = os.path.join(log_dir, "crash_log.txt")
    app_log = os.path.join(log_dir, "app_main.log")

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s',
        handlers=[
            RotatingFileHandler(
                app_log, maxBytes=2 * 1024 * 1024, backupCount=3, encoding='utf-8'
            ),
            logging.StreamHandler(sys.stdout)
        ]
    )

    def _write_crash(text):
        try:
            with open(crash_log, "a", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass

    def _log_exception(exctype, value, tb):
        import io
        from data_manager import db_log_crash

        buf = io.StringIO()
        traceback.print_exception(exctype, value, tb, file=buf)
        err_text = buf.getvalue()
        
        logging.critical(f"Unhandled exception:\n{err_text}")
        
        _write_crash("\n---\n" + err_text)
        try:
            db_log_crash(err_text)
        except Exception:
            pass
        sys.__excepthook__(exctype, value, tb)

    sys.excepthook = _log_exception

    if hasattr(threading, "excepthook"):
        def _thread_exception(args):
            _log_exception(args.exc_type, args.exc_value, args.exc_traceback)

        threading.excepthook = _thread_exception

    try:
        import faulthandler

        crash_file = open(crash_log, "a", encoding="utf-8")
        faulthandler.enable(file=crash_file, all_threads=True)
    except Exception:
        pass

    # Initialize unified SQLite data manager
    try:
        from data_manager import init_db
        init_db()
    except Exception as e:
        print(f"Failed to initialize SQLite database: {e}")

    setup_autorun()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    style_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.qss")
    if os.path.exists(style_path):
        with open(style_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
            
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
