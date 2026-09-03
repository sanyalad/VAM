"""
toast_widget.py — Тост-уведомления (auto-dismiss) для PyQt6.

Использование:
    Toast.success(parent, "Файл сохранён")
    Toast.warning(parent, "Принтер занят")
    Toast.error(parent, "Ошибка генерации")
"""

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QApplication
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QPoint, QEasingCurve


class ToastWidget(QFrame):
    """Всплывающее уведомление поверх родительского окна."""

    LEVEL_COLORS = {
        "success": ("#2B8A3E", "#EBFBEE", "#B2F2BB"),
        "warning": ("#E67700", "#FFF3BF", "#FFD43B"),
        "error":   ("#C92A2A", "#FFE3E3", "#FFA8A8"),
        "info":    ("#1971C2", "#E7F5FF", "#74C0FC"),
    }

    def __init__(self, parent, message: str, level: str = "info", duration_ms: int = 3500):
        super().__init__(parent)
        self.setObjectName("toast_frame")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        text_color, bg_color, border_color = self.LEVEL_COLORS.get(level, self.LEVEL_COLORS["info"])
        icons = {"success": "✅", "warning": "⚠️", "error": "❌", "info": "ℹ️"}
        icon = icons.get(level, "ℹ️")

        self.setStyleSheet(f"""
            QFrame#toast_frame {{
                background-color: {bg_color};
                border: 1.5px solid {border_color};
                border-radius: 10px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(10)

        lbl_icon = QLabel(icon)
        lbl_icon.setStyleSheet("font-size: 16px; background: transparent;")
        layout.addWidget(lbl_icon)

        lbl_text = QLabel(message)
        lbl_text.setStyleSheet(
            f"color: {text_color}; font-size: 10pt; font-weight: 600; "
            "background: transparent; max-width: 400px;"
        )
        lbl_text.setWordWrap(True)
        layout.addWidget(lbl_text, stretch=1)

        self.adjustSize()
        self._position_toast()

        # Анимация появления
        self._anim_in = QPropertyAnimation(self, b"pos")
        self._anim_in.setDuration(200)
        self._anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_in.setStartValue(QPoint(self.x(), self.y() + 20))
        self._anim_in.setEndValue(QPoint(self.x(), self.y()))
        self._anim_in.start()

        # Авто-скрытие
        QTimer.singleShot(duration_ms, self._slide_out)

    def _position_toast(self):
        """Расположить тост в нижнем правом углу родителя."""
        parent = self.parentWidget()
        if parent:
            pw, ph = parent.width(), parent.height()
            margin = 20
            self.move(pw - self.width() - margin, ph - self.height() - margin)

    def _slide_out(self):
        self._anim_out = QPropertyAnimation(self, b"pos")
        self._anim_out.setDuration(180)
        self._anim_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim_out.setStartValue(self.pos())
        self._anim_out.setEndValue(QPoint(self.x(), self.y() + 20))
        self._anim_out.finished.connect(self.deleteLater)
        self._anim_out.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_toast()


class Toast:
    """Фабрика тост-уведомлений."""

    @staticmethod
    def success(parent, message: str, duration_ms: int = 3000):
        t = ToastWidget(parent, message, "success", duration_ms)
        t.show()
        t.raise_()
        return t

    @staticmethod
    def warning(parent, message: str, duration_ms: int = 4000):
        t = ToastWidget(parent, message, "warning", duration_ms)
        t.show()
        t.raise_()
        return t

    @staticmethod
    def error(parent, message: str, duration_ms: int = 5000):
        t = ToastWidget(parent, message, "error", duration_ms)
        t.show()
        t.raise_()
        return t

    @staticmethod
    def info(parent, message: str, duration_ms: int = 3000):
        t = ToastWidget(parent, message, "info", duration_ms)
        t.show()
        t.raise_()
        return t
