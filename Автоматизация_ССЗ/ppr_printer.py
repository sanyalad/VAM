import os
import re
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QSpinBox, QPushButton, QMessageBox, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt


PPR_FORMS = (
    ("Спецсталь — обычный ППР", "Бланк для ППР 2026  Спецсталь.doc"),
    ("Спецсталь — МЭО", "Бланк  для ППР МЭО 2026 Спецсталь.doc"),
    ("ИСМ — обычный ППР", "Бланк для ППР 2026  ИСМ.doc"),
    ("КАРТЭКС — обычный ППР", "Бланк для ППР 2026 КАРТЭКС.doc"),
    ("КАРТЭКС — МЭО", "Бланк  для ППР  МЭО 2026 КАРТЭКС.doc"),
    ("Ижора — обычный ППР", "Бланк для ППР 2026  Ижора.doc"),
    ("Ижора — МЭО", "Бланк  для ППР  МЭО 2026 ИЖОРА.doc"),
)


def ppr_form_for_task(task):
    """Возвращает (название, файл) для задания либо None при неизвестном цехе."""
    context = " ".join(
        str(task.get(key) or "")
        for key in ("place", "source_sheet", "source_file")
    ).lower().replace("ё", "е")
    work = str(task.get("work") or "").lower().replace("ё", "е")
    is_meo = "мэо" in work or "мео" in work

    if "исм" in context or re.search(r"(?:цех\s*(?:№\s*)?)?92\b", context):
        family = "ИСМ"
    elif any(token in context for token in ("ижора", "печь 10", "п.10", "66.1", "34/66")):
        family = "Ижора"
    elif "картэкс" in context or re.search(r"цех\s*(?:№\s*)?(?:2|6)\b", context):
        family = "КАРТЭКС"
    elif (
        "спецсталь" in context
        or re.search(r"цех\s*(?:№\s*)?(?:47|66)\b", context)
        or "66.2" in context
        or "66-2" in context
    ):
        family = "Спецсталь"
    else:
        return None

    wanted = f"{family} — {'МЭО' if is_meo and family != 'ИСМ' else 'обычный ППР'}"
    return next((item for item in PPR_FORMS if item[0] == wanted), None)


class PprPrintDialog(QDialog):
    FORMS = PPR_FORMS

    def __init__(self, parent=None, initial_counts=None, lock_counts=False):
        super().__init__(parent)
        self.setWindowTitle("Печать бланков ППР")
        self.resize(680, 520)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        initial_counts = dict(initial_counts or {})
        info = QLabel(
            "Формы и количество рассчитаны по выбранным заданиям ППР. "
            "Будет напечатан один бланк на каждое выбранное задание."
            if lock_counts else
            "Отметьте все нужные формы — они будут отправлены на печать одним пакетом. "
            "Количество задаётся отдельно для каждой формы."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.forms_table = QTableWidget(len(self.FORMS), 3)
        self.forms_table.setHorizontalHeaderLabels(["Печатать", "Форма", "Копий"])
        self.forms_table.verticalHeader().setVisible(False)
        header = self.forms_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for row, (label, filename) in enumerate(self.FORMS):
            check = QCheckBox()
            check.setStyleSheet("margin-left:18px;")
            check.setChecked(initial_counts.get(filename, 0) > 0)
            check.setEnabled(not lock_counts)
            self.forms_table.setCellWidget(row, 0, check)
            item = QTableWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, filename)
            self.forms_table.setItem(row, 1, item)
            copies = QSpinBox()
            copies.setRange(1, 999)
            copies.setValue(max(1, int(initial_counts.get(filename, 1))))
            copies.setEnabled(not lock_counts)
            self.forms_table.setCellWidget(row, 2, copies)
        layout.addWidget(self.forms_table)

        quick = QHBoxLayout()
        btn_all_regular = QPushButton("Выбрать обычные формы")
        btn_all_regular.clicked.connect(self._select_regular)
        btn_clear = QPushButton("Снять выбор")
        btn_clear.clicked.connect(lambda: self._set_all(False))
        quick.addWidget(btn_all_regular)
        quick.addWidget(btn_clear)
        quick.addStretch()
        if lock_counts:
            btn_all_regular.hide()
            btn_clear.hide()
        layout.addLayout(quick)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)

        btn_print = QPushButton("Печать")
        btn_print.setObjectName("btn_primary")
        btn_print.clicked.connect(self.accept)

        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_print)
        layout.addLayout(btn_layout)

    def _set_all(self, checked):
        for row in range(self.forms_table.rowCount()):
            self.forms_table.cellWidget(row, 0).setChecked(checked)

    def _select_regular(self):
        for row, (label, _filename) in enumerate(self.FORMS):
            self.forms_table.cellWidget(row, 0).setChecked("обычный" in label)

    def get_data(self):
        selected = []
        for row in range(self.forms_table.rowCount()):
            if not self.forms_table.cellWidget(row, 0).isChecked():
                continue
            item = self.forms_table.item(row, 1)
            selected.append({
                "label": item.text(),
                "filename": item.data(Qt.ItemDataRole.UserRole),
                "copies": self.forms_table.cellWidget(row, 2).value(),
            })
        return selected

    def accept(self):
        selected = self.get_data()
        if not selected:
            QMessageBox.information(self, "Печать", "Выберите хотя бы одну форму.")
            return
        base_dir = os.path.dirname(os.path.abspath(__file__))
        missing = [item["filename"] for item in selected if not os.path.exists(os.path.join(base_dir, "БЛАНКИ_ППР", item["filename"]))]
        if missing:
            QMessageBox.warning(self, "Не найдены формы", "\n".join(missing))
            return
        printed = 0
        for item in selected:
            file_path = os.path.join(base_dir, "БЛАНКИ_ППР", item["filename"])
            if not self._print_word_doc(file_path, item["copies"]):
                return
            printed += item["copies"]
        QMessageBox.information(
            self, "Печать", f"В очередь отправлено форм: {len(selected)}, листов: {printed}."
        )
        super().accept()

    def _print_word_doc(self, file_path, copies):
        """Печать .doc файла с гибридной стратегией для исключения 0x800706ba/be."""
        abs_path = os.path.abspath(file_path)
        printed_ok = False

        # Основной способ: Windows Shell print (быстро, не использует COM-апартаменты)
        try:
            for _ in range(copies):
                os.startfile(abs_path, "print")
            printed_ok = True
        except Exception:
            # Резервный способ: Word COM Automation с отключением интерактивных диалогов
            com_ok = False
            word = None
            doc = None
            try:
                try:
                    import pythoncom
                    try:
                        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
                    except Exception:
                        pythoncom.CoInitialize()
                    com_ok = True
                except Exception:
                    pass

                import win32com.client
                word = win32com.client.DispatchEx("Word.Application")
                word.Visible = False
                try:
                    word.DisplayAlerts = 0
                except Exception:
                    pass
                doc = word.Documents.Open(abs_path, ReadOnly=True)
                for _ in range(copies):
                    word.PrintOut(Background=False)
                try:
                    doc.Close(False)
                except Exception:
                    pass
                doc = None
                printed_ok = True
            except Exception as e:
                QMessageBox.critical(
                    self, "Ошибка печати", f"Не удалось распечатать файл.\n\n{e}"
                )
            finally:
                if word is not None:
                    try:
                        word.Quit()
                    except Exception:
                        pass
                    word = None
                doc = None
                import gc
                gc.collect()
                if com_ok:
                    try:
                        import pythoncom
                        # pythoncom.CoUninitialize()
                        pass
                    except Exception:
                        pass

        if printed_ok:
            return True
        return False
