import os
import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsItem,
    QMessageBox, QInputDialog, QFileDialog, QColorDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF, QObject
from PyQt6.QtGui import QPixmap, QPen, QBrush, QColor, QPainter, QCursor

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemes_config.json")

def load_schemes_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_schemes_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

DEFAULT_BLOCKS_66 = [
    {"name": "1", "shape": "rect", "x": 198, "y": 110, "w": 30, "h": 60, "color": "#E65100"},
    {"name": "2", "shape": "rect", "x": 241, "y": 126, "w": 28, "h": 44, "color": "#E65100"},
    {"name": "3", "shape": "rect", "x": 283, "y": 110, "w": 30, "h": 60, "color": "#E65100"},
    {"name": "5", "shape": "rect", "x": 198, "y": 212, "w": 17, "h": 32, "color": "#E65100"},
    {"name": "4", "shape": "circle", "x": 383, "y": 172, "w": 36, "h": 36, "color": "#FF0000"},
    {"name": "3/Б", "shape": "rect", "x": 425, "y": 170, "w": 42, "h": 30, "color": "#03A9F4"},
    {"name": "10 ц,6", "shape": "rect", "x": 325, "y": 271, "w": 58, "h": 30, "color": "#E65100"},
    {"name": "ГРУ", "shape": "rect", "x": 60, "y": 50, "w": 60, "h": 30, "color": "#B3E5FC", "is_static": True},
    {"name": "Кладовка КИП", "shape": "rect", "x": 350, "y": 110, "w": 120, "h": 45, "color": "#FFF59D", "is_static": False},
]

DEFAULT_BLOCKS_47 = [
    {"name": "34", "shape": "rect", "x": 35, "y": 118, "w": 38, "h": 48, "color": "#FFFFFF"},
    {"name": "33", "shape": "rect", "x": 81, "y": 118, "w": 51, "h": 48, "color": "#FFFFFF"},
    {"name": "32", "shape": "rect", "x": 141, "y": 118, "w": 58, "h": 48, "color": "#FFFFFF"},
    {"name": "31", "shape": "rect", "x": 213, "y": 118, "w": 58, "h": 48, "color": "#FFFFFF"},
    {"name": "30", "shape": "rect", "x": 353, "y": 86, "w": 28, "h": 30, "color": "#8D6E63"},
    {"name": "29", "shape": "rect", "x": 382, "y": 140, "w": 26, "h": 30, "color": "#8D6E63"},
    {"name": "АКК 12000ТС", "shape": "circle", "x": 510, "y": 84, "w": 58, "h": 112, "color": "#4CAF50", "is_static": True},
    {"name": "27", "shape": "rect", "x": 620, "y": 125, "w": 26, "h": 31, "color": "#8D6E63"},
    {"name": "26", "shape": "rect", "x": 652, "y": 125, "w": 26, "h": 31, "color": "#8D6E63"},
    {"name": "25", "shape": "rect", "x": 686, "y": 125, "w": 26, "h": 31, "color": "#8D6E63"},
    {"name": "24", "shape": "rect", "x": 718, "y": 125, "w": 26, "h": 31, "color": "#8D6E63"},
    {"name": "23", "shape": "rect", "x": 752, "y": 125, "w": 26, "h": 31, "color": "#8D6E63"},
    {"name": "ГРУ", "shape": "rect", "x": 790, "y": 115, "w": 20, "h": 80, "color": "#03A9F4", "is_static": True},
    {"name": "1", "shape": "rect", "x": 43, "y": 395, "w": 22, "h": 31, "color": "#FF0000"},
    {"name": "2", "shape": "rect", "x": 70, "y": 395, "w": 22, "h": 31, "color": "#FF0000"},
    {"name": "3", "shape": "rect", "x": 96, "y": 395, "w": 22, "h": 31, "color": "#FF0000"},
    {"name": "4", "shape": "rect", "x": 124, "y": 395, "w": 22, "h": 31, "color": "#FF0000"},
    {"name": "5", "shape": "rect", "x": 150, "y": 395, "w": 22, "h": 31, "color": "#FFD54F"},
    {"name": "6", "shape": "rect", "x": 177, "y": 395, "w": 22, "h": 31, "color": "#FF0000"},
    {"name": "7", "shape": "rect", "x": 212, "y": 395, "w": 22, "h": 31, "color": "#FF0000"},
    {"name": "8", "shape": "rect", "x": 245, "y": 395, "w": 22, "h": 31, "color": "#FF0000"},
    {"name": "9", "shape": "rect", "x": 271, "y": 395, "w": 22, "h": 31, "color": "#FF0000"},
    {"name": "10", "shape": "rect", "x": 298, "y": 395, "w": 22, "h": 31, "color": "#FF0000"},
    {"name": "11", "shape": "rect", "x": 324, "y": 395, "w": 22, "h": 31, "color": "#FFD54F"},
    {"name": "12", "shape": "rect", "x": 350, "y": 395, "w": 22, "h": 31, "color": "#FF0000"},
    {"name": "13", "shape": "rect", "x": 376, "y": 395, "w": 22, "h": 31, "color": "#FFD54F"},
    {"name": "14", "shape": "rect", "x": 403, "y": 395, "w": 22, "h": 31, "color": "#FF0000"},
    {"name": "15", "shape": "rect", "x": 430, "y": 436, "w": 22, "h": 28, "color": "#8D6E63"},
    {"name": "16", "shape": "rect", "x": 471, "y": 395, "w": 22, "h": 31, "color": "#8D6E63"},
    {"name": "17", "shape": "rect", "x": 495, "y": 395, "w": 22, "h": 31, "color": "#FFD54F"},
    {"name": "АКК 6000ТС", "shape": "circle", "x": 522, "y": 368, "w": 48, "h": 92, "color": "#4CAF50", "is_static": True},
    {"name": "18", "shape": "rect", "x": 645, "y": 395, "w": 22, "h": 31, "color": "#8D6E63"},
    {"name": "19", "shape": "rect", "x": 671, "y": 395, "w": 22, "h": 31, "color": "#8D6E63"},
    {"name": "20", "shape": "rect", "x": 697, "y": 395, "w": 22, "h": 31, "color": "#8D6E63"},
    {"name": "21", "shape": "rect", "x": 723, "y": 395, "w": 22, "h": 31, "color": "#8D6E63"},
    {"name": "22", "shape": "rect", "x": 749, "y": 395, "w": 22, "h": 31, "color": "#FFD54F"},
    {"name": "ГРУ 2", "shape": "rect", "x": 790, "y": 380, "w": 20, "h": 80, "color": "#03A9F4", "is_static": True},
    {"name": "КЛ-ка", "shape": "rect", "x": 750, "y": 450, "w": 45, "h": 40, "color": "#E3F2FD", "is_static": False},
]

class SchemeBlockGraphicsItem(QGraphicsItem):
    def __init__(self, rect, name="Новый блок", shape_type="rect", color="#E65100", loc_id=None, is_static=False):
        super().__init__()
        self._rect = QRectF(rect)
        self.name = name
        self.shape_type = shape_type
        self.color_hex = color
        self.loc_id = loc_id
        
        # Auto-detect decorative static items (АКК, ГРУ)
        # Note: Кладовка КИП, Мастерская КИП и КЛ-ка являются кладовками и ДОЛЖНЫ быть кликабельными
        if is_static or any(k in str(name).upper() for k in ["АКК", "ГРУ"]):
            self.is_static = True
        else:
            self.is_static = False

        self.is_edit_mode = False
        self._is_hovered = False
        self._resizing = False
        self._resize_corner = None
        self._drag_start_pos = None
        self._drag_start_rect = None
        
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(10)

    def set_edit_mode(self, enabled):
        self.is_edit_mode = enabled
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, enabled)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, enabled)
        self.update()

    def boundingRect(self):
        return self._rect.adjusted(-12, -12, 12, 12)

    def _get_handle_rects(self):
        r = self._rect
        s = 8
        return {
            'tl': QRectF(r.left() - s/2, r.top() - s/2, s, s),
            'tr': QRectF(r.right() - s/2, r.top() - s/2, s, s),
            'bl': QRectF(r.left() - s/2, r.bottom() - s/2, s, s),
            'br': QRectF(r.right() - s/2, r.bottom() - s/2, s, s),
        }

    def hoverMoveEvent(self, event):
        if self.is_edit_mode and self.isSelected():
            pos = event.pos()
            handles = self._get_handle_rects()
            for corner, hr in handles.items():
                if hr.contains(pos):
                    if corner in ('tl', 'br'):
                        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                    else:
                        self.setCursor(Qt.CursorShape.SizeBDiagCursor)
                    return
        if not self.is_edit_mode:
            if not self.is_static:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor if self.isSelected() else Qt.CursorShape.PointingHandCursor)
        super().hoverMoveEvent(event)

    def hoverEnterEvent(self, event):
        self._is_hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._is_hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if self.is_edit_mode and event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            handles = self._get_handle_rects()
            for corner, hr in handles.items():
                if hr.contains(pos):
                    self._resizing = True
                    self._resize_corner = corner
                    self._drag_start_pos = event.scenePos()
                    self._drag_start_rect = QRectF(self._rect)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing and self._drag_start_pos and self._drag_start_rect:
            diff = event.scenePos() - self._drag_start_pos
            r = QRectF(self._drag_start_rect)
            c = self._resize_corner
            
            min_size = 15
            if 'r' in c:
                r.setRight(max(r.left() + min_size, r.right() + diff.x()))
            if 'l' in c:
                r.setLeft(min(r.right() - min_size, r.left() + diff.x()))
            if 'b' in c:
                r.setBottom(max(r.top() + min_size, r.bottom() + diff.y()))
            if 't' in c:
                r.setTop(min(r.bottom() - min_size, r.top() + diff.y()))
                
            self.prepareGeometryChange()
            self._rect = r
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            self._resize_corner = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        color = QColor(self.color_hex)
        if self._is_hovered and not self.is_edit_mode and not self.is_static:
            fill_color = QColor(255, 152, 0, 220)
            pen = QPen(QColor(255, 152, 0), 3)
        elif self.isSelected() and self.is_edit_mode:
            fill_color = QColor(color.red(), color.green(), color.blue(), 170)
            pen = QPen(QColor(33, 150, 243), 2, Qt.PenStyle.DashLine)
        else:
            alpha = 220 if not self.is_static else 120
            fill_color = QColor(color.red(), color.green(), color.blue(), alpha)
            border_color = color.darker(150) if color.name() != "#ffffff" else QColor("#333")
            pen = QPen(border_color, 2)
            
        painter.setPen(pen)
        painter.setBrush(QBrush(fill_color))
        
        if self.shape_type == "circle":
            painter.drawEllipse(self._rect)
        else:
            painter.drawRoundedRect(self._rect, 6, 6)
            
        painter.setPen(QPen(QColor("#000000") if fill_color.lightness() > 160 else QColor("#ffffff")))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(self._rect, Qt.AlignmentFlag.AlignCenter, self.name)
        
        if self.is_edit_mode and self.isSelected():
            painter.setPen(QPen(QColor(33, 150, 243), 1))
            painter.setBrush(QBrush(QColor(255, 255, 255)))
            for hr in self._get_handle_rects().values():
                painter.drawRect(hr)

class InteractiveSchemeView(QGraphicsView):
    location_clicked = pyqtSignal(object, object)
    item_double_clicked = pyqtSignal(object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setStyleSheet("background: #F8F9FA; border: 1px solid #CCC; border-radius: 8px;")
        
    def resizeEvent(self, event):
        super().resizeEvent(event)

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            factor = 1.15
        else:
            factor = 0.85
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if isinstance(item, SchemeBlockGraphicsItem):
            if not item.is_edit_mode and event.button() == Qt.MouseButton.LeftButton:
                if not item.is_static:
                    self.location_clicked.emit(item.loc_id, item.name)
                    return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.pos())
        if isinstance(item, SchemeBlockGraphicsItem) and item.is_edit_mode:
            self.item_double_clicked.emit(item)
            return
        super().mouseDoubleClickEvent(event)

def find_loc(item_name, locations):
    for loc in locations:
        if loc["name"].strip() == item_name:
            return loc
    for loc in locations:
        parts = loc["name"].split()
        if item_name in parts:
            return loc
    for loc in locations:
        if item_name in loc["name"]:
            return loc
    return None

class SchemeEditorWidget(QWidget):
    def __init__(self, ws_id, ws_name, locations, parent=None):
        super().__init__(parent)
        self.ws_id = str(ws_id)
        self.ws_name = ws_name
        self.locations = [loc for loc in locations if loc["type"] != "unassigned"]
        self.is_edit_mode = False
        self.pixmap_item = None
        self.current_image_path = None
        
        self.view = InteractiveSchemeView(self)
        self.view.item_double_clicked.connect(self.edit_block_dialog)
        
        self.setup_ui()
        self.load_scheme()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.toolbar = QHBoxLayout()
        self.toolbar.setContentsMargins(5, 5, 5, 5)
        
        self.lbl_title = QLabel(f"<b>Интерактивная схема цеха: {self.ws_name}</b>")
        self.lbl_title.setStyleSheet("font-size: 16px; color: #333;")
        self.toolbar.addWidget(self.lbl_title)
        
        self.btn_zoom_in = QPushButton("🔍 +")
        self.btn_zoom_in.setToolTip("Приблизить схему")
        self.btn_zoom_in.clicked.connect(self.zoom_in)
        
        self.btn_zoom_out = QPushButton("🔍 -")
        self.btn_zoom_out.setToolTip("Отдалить схему")
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        
        self.btn_zoom_reset = QPushButton("↺ 100%")
        self.btn_zoom_reset.setToolTip("Сбросить масштаб к размеру окна")
        self.btn_zoom_reset.clicked.connect(self.zoom_reset)
        
        self.toolbar.addWidget(self.btn_zoom_in)
        self.toolbar.addWidget(self.btn_zoom_out)
        self.toolbar.addWidget(self.btn_zoom_reset)
        
        self.btn_mode = QPushButton("✏ Режим редактирования ( Paint )")
        self.btn_mode.setCheckable(True)
        self.btn_mode.clicked.connect(self.toggle_edit_mode)
        self.toolbar.addWidget(self.btn_mode)
        
        self.edit_actions = QWidget()
        edit_layout = QHBoxLayout(self.edit_actions)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        
        self.btn_add_rect = QPushButton("➕ Прямоугольник")
        self.btn_add_rect.clicked.connect(lambda: self.add_new_block("rect"))
        
        self.btn_add_circle = QPushButton("⭕ Круг")
        self.btn_add_circle.clicked.connect(lambda: self.add_new_block("circle"))
        
        self.btn_bind = QPushButton("🔗 Привязать место")
        self.btn_bind.clicked.connect(self.bind_selected_block)
        
        self.btn_delete = QPushButton("🗑 Удалить")
        self.btn_delete.clicked.connect(self.delete_selected_block)
        
        self.btn_img = QPushButton("🖼 Загрузить PNG (опционально)")
        self.btn_img.clicked.connect(self.choose_bg_image)
        
        self.btn_save = QPushButton("💾 Сохранить схему")
        self.btn_save.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.btn_save.clicked.connect(self.save_scheme)
        
        edit_layout.addWidget(self.btn_add_rect)
        edit_layout.addWidget(self.btn_add_circle)
        edit_layout.addWidget(self.btn_bind)
        edit_layout.addWidget(self.btn_delete)
        edit_layout.addWidget(self.btn_img)
        edit_layout.addWidget(self.btn_save)
        
        self.toolbar.addWidget(self.edit_actions)
        self.edit_actions.setVisible(False)
        self.toolbar.addStretch()
        
        layout.addLayout(self.toolbar)
        layout.addWidget(self.view)

    def zoom_in(self):
        self.view.scale(1.2, 1.2)
        
    def zoom_out(self):
        self.view.scale(0.8, 0.8)
        
    def zoom_reset(self):
        self.view.resetTransform()
        if self.view.scene and not self.view.scene.sceneRect().isEmpty():
            self.view.fitInView(self.view.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def toggle_edit_mode(self, checked):
        self.is_edit_mode = checked
        self.edit_actions.setVisible(checked)
        if checked:
            self.btn_mode.setText("✏ Режим редактирования (ВКЛ)")
            self.btn_mode.setStyleSheet("background-color: #FF9800; color: white; font-weight: bold;")
            self.view.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.view.setToolTip("Перетаскивайте блоки мышкой, тяните за углы для изменения размера, двухклик для настройки")
        else:
            self.btn_mode.setText("✏ Режим редактирования ( Paint )")
            self.btn_mode.setStyleSheet("")
            self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.view.setToolTip("Зажмите ЛКМ для перемещения схемы, используйте колесо мыши для приближения. Клик по печи/кладовке открывает её данные.")
            
        for item in self.view.scene.items():
            if isinstance(item, SchemeBlockGraphicsItem):
                item.set_edit_mode(checked)

    def load_scheme(self):
        self.view.scene.clear()
        self.pixmap_item = None
        
        config = load_schemes_config()
        ws_id_str = str(self.ws_id)
        ws_name_str = str(self.ws_name)
        
        ws_config = (
            config.get(ws_id_str)
            or config.get(ws_name_str)
            or next((v for k, v in config.items() if ws_name_str and k in ws_name_str), {})
        )
        
        img_path = ws_config.get("image_path", "")
        self.current_image_path = img_path
        
        # Fixed clean scene area
        self.view.scene.setSceneRect(0, 0, 842, 550)
        
        # Render clean vector background structures
        ws_str = ws_id_str
        ws_name_lower = ws_name_str.lower()
        
        # Outer shop wall border
        outer_rect = self.view.scene.addRect(15, 15, 812, 510, QPen(QColor("#222222"), 2), QBrush(QColor("#FAFAFA")))
        outer_rect.setZValue(0)
        
        if "47" in ws_str or "47" in ws_name_lower or ws_str == "2":
            line1 = self.view.scene.addLine(15, 210, 827, 210, QPen(QColor("#333333"), 2))
            line2 = self.view.scene.addLine(15, 350, 827, 350, QPen(QColor("#333333"), 2))
            line1.setZValue(1)
            line2.setZValue(1)
            
            txt_estakada = self.view.scene.addSimpleText("Э С Т А К А Д А")
            txt_estakada.setBrush(QBrush(QColor("#777777")))
            font = txt_estakada.font()
            font.setBold(True)
            font.setPointSize(16)
            txt_estakada.setFont(font)
            txt_estakada.setPos(350, 265)
            txt_estakada.setZValue(1)
            
        elif "66" in ws_str or "66" in ws_name_lower or ws_str == "1":
            line = self.view.scene.addLine(15, 330, 827, 330, QPen(QColor("#333333"), 2))
            line.setZValue(1)
            
            txt_title = self.view.scene.addSimpleText("План расположения КИП ц.№66 (участок-2)")
            txt_title.setBrush(QBrush(QColor("#333333")))
            font = txt_title.font()
            font.setBold(True)
            font.setPointSize(14)
            txt_title.setFont(font)
            txt_title.setPos(250, 30)
            txt_title.setZValue(1)

        # Load blocks
        blocks_data = ws_config.get("blocks")
        if blocks_data is None:
            if "66" in ws_str or "66" in ws_name_lower or ws_str == "1":
                blocks_data = DEFAULT_BLOCKS_66
            elif "47" in ws_str or "47" in ws_name_lower or ws_str == "2":
                blocks_data = DEFAULT_BLOCKS_47
            else:
                blocks_data = []
                
        for b in blocks_data:
            name = b.get("name", "Блок")
            shape = b.get("shape", "rect")
            color = b.get("color", "#E65100")
            x = b.get("x", 100)
            y = b.get("y", 100)
            w = b.get("w", 50)
            h = b.get("h", 50)
            is_st = b.get("is_static", False)
            
            matched_loc = find_loc(name, self.locations)
            loc_id = matched_loc["id"] if matched_loc else b.get("location_id")
            
            item = SchemeBlockGraphicsItem(QRectF(0, 0, w, h), name, shape, color, loc_id, is_static=is_st)
            item.setPos(x, y)
            item.set_edit_mode(self.is_edit_mode)
            self.view.scene.addItem(item)
            
        self.zoom_reset()

    def add_new_block(self, shape_type="rect"):
        center = self.view.scene.sceneRect().center()
        item = SchemeBlockGraphicsItem(QRectF(0, 0, 60, 40), "Новый блок", shape_type, "#E65100")
        item.setPos(center.x() - 30, center.y() - 20)
        item.set_edit_mode(True)
        self.view.scene.addItem(item)
        item.setSelected(True)

    def bind_selected_block(self):
        items = self.view.scene.selectedItems()
        if not items or not isinstance(items[0], SchemeBlockGraphicsItem):
            QMessageBox.information(self, "Выделение", "Сначала выделите кликом блок на схеме.")
            return
        self.edit_block_dialog(items[0])

    def edit_block_dialog(self, item):
        if not isinstance(item, SchemeBlockGraphicsItem):
            return
            
        loc_options = ["( Без привязки )"] + [f"{l['name']} (ID: {l['id']})" for l in self.locations]
        
        curr_name = item.name
        new_name, ok1 = QInputDialog.getText(self, "Название блока", "Введите отображаемое имя блока:", text=curr_name)
        if not ok1:
            return
            
        loc_str, ok2 = QInputDialog.getItem(self, "Привязка к месту", "Выберите место из базы данных:", loc_options, 0, False)
        
        color = QColorDialog.getColor(QColor(item.color_hex), self, "Выберите цвет блока")
        
        item.name = new_name.strip() or item.name
        if ok2 and loc_str and "(ID:" in loc_str:
            try:
                item.loc_id = int(loc_str.split("(ID: ")[-1].replace(")", ""))
            except:
                pass
        elif ok2 and loc_str == "( Без привязки )":
            item.loc_id = None
            
        if color.isValid():
            item.color_hex = color.name()
            
        item.update()

    def delete_selected_block(self):
        items = self.view.scene.selectedItems()
        for item in items:
            if isinstance(item, SchemeBlockGraphicsItem):
                self.view.scene.removeItem(item)

    def choose_bg_image(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл схемы (PNG/JPG)", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if filepath:
            self.current_image_path = filepath
            config = load_schemes_config()
            ws_id_str = str(self.ws_id)
            ws_name_str = str(self.ws_name)
            if ws_id_str not in config:
                config[ws_id_str] = {}
            config[ws_id_str]["image_path"] = filepath
            if ws_name_str:
                config[ws_name_str]["image_path"] = filepath
            save_schemes_config(config)
            self.load_scheme()

    def save_scheme(self):
        config = load_schemes_config()
        ws_id_str = str(self.ws_id)
        ws_name_str = str(self.ws_name)
        
        ws_dict = {
            "image_path": self.current_image_path or "",
            "blocks": []
        }
            
        for item in self.view.scene.items():
            if isinstance(item, SchemeBlockGraphicsItem):
                pos = item.pos()
                r = item._rect
                ws_dict["blocks"].append({
                    "name": item.name,
                    "shape": item.shape_type,
                    "x": pos.x() + r.x(),
                    "y": pos.y() + r.y(),
                    "w": r.width(),
                    "h": r.height(),
                    "color": item.color_hex,
                    "location_id": item.loc_id,
                    "is_static": item.is_static
                })
                
        config[ws_id_str] = ws_dict
        if ws_name_str:
            config[ws_name_str] = ws_dict
            
        save_schemes_config(config)
        QMessageBox.information(self, "Сохранено", "Схема и блоки успешно сохранены!")
