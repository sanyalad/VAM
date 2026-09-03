import random
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QRadioButton, QButtonGroup, QScrollArea, QFrame,
    QMessageBox, QProgressBar, QTextEdit, QGroupBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from exam_registry import EXAM_MODULES, load_exam_module, save_progress_entry, load_progress, save_all_progress
from ssz_config import CONFIG

MODE_BY_TICKET = "by_ticket"
MODE_RANDOM = "random"
MODE_STUDY = "study"
MODE_EXAM = "exam"
MODE_MISTAKES = "mistakes"

MODE_LABELS = {
    MODE_BY_TICKET: "По билету",
    MODE_RANDOM: "Случайный билет",
    MODE_STUDY: "Учебный режим",
    MODE_EXAM: "Экзамен",
    MODE_MISTAKES: "Работа над ошибками",
}


class ExamHubWidget(QWidget):
    start_session = pyqtSignal(str, str, object)
    go_home = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._module_id = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        top = QHBoxLayout()
        btn_back = QPushButton("← На главную")
        btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_back.clicked.connect(self.go_home.emit)
        top.addWidget(btn_back)
        top.addStretch()
        layout.addLayout(top)

        title = QLabel("Электробезопасность")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #005A9E;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        hint = QLabel(
            "ПТБ и тесты на III группу — одна подготовка, разный формат:\n"
            "• тесты — выбор ответа, как на экзамене;\n"
            "• ПТБ — билеты с текстовыми ответами для заучивания правил."
        )
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #555; font-size: 12px; margin-bottom: 8px;")
        layout.addWidget(hint)

        modules_box = QGroupBox("Выберите формат подготовки")
        modules_box.setStyleSheet("QGroupBox { font-weight: bold; }")
        mod_layout = QVBoxLayout(modules_box)

        self.module_buttons = []
        for module in EXAM_MODULES:
            row = QHBoxLayout()
            btn = QPushButton(module["title"])
            btn.setFixedHeight(52)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if module.get("enabled"):
                btn.setStyleSheet(
                    "background-color: #0078D7; color: white; font-weight: bold; "
                    "font-size: 13px; border-radius: 5px; text-align: left; padding-left: 16px;"
                )
                btn.clicked.connect(lambda _, m=module: self._select_module(m))
            sub = QLabel(module.get("subtitle", ""))
            sub.setStyleSheet("color: #666; font-size: 11px;")
            col = QVBoxLayout()
            col.addWidget(btn)
            col.addWidget(sub)
            row.addLayout(col, stretch=1)
            mod_layout.addLayout(row)
            self.module_buttons.append(btn)

        layout.addWidget(modules_box)

        self.settings_box = QGroupBox("Режим прохождения")
        self.settings_box.setStyleSheet("QGroupBox { font-weight: bold; }")
        self.settings_box.setEnabled(False)
        settings_layout = QVBoxLayout(self.settings_box)

        mode_row = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(MODE_LABELS[MODE_BY_TICKET], MODE_BY_TICKET)
        self.mode_combo.addItem(MODE_LABELS[MODE_RANDOM], MODE_RANDOM)
        self.mode_combo.addItem(MODE_LABELS[MODE_STUDY], MODE_STUDY)
        self.mode_combo.addItem(MODE_LABELS[MODE_EXAM], MODE_EXAM)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(QLabel("Режим:"))
        mode_row.addWidget(self.mode_combo, stretch=1)
        settings_layout.addLayout(mode_row)

        ticket_row = QHBoxLayout()
        ticket_row.addWidget(QLabel("Билет №:"))
        self.ticket_combo = QComboBox()
        ticket_row.addWidget(self.ticket_combo, stretch=1)
        settings_layout.addLayout(ticket_row)

        self.lbl_selected = QLabel("")
        self.lbl_selected.setStyleSheet("color: #005A9E; font-weight: bold;")
        settings_layout.addWidget(self.lbl_selected)

        self.btn_mistakes = QPushButton("Работа над ошибками")
        self.btn_mistakes.setFixedHeight(48)
        self.btn_mistakes.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mistakes.setStyleSheet(
            "background-color: #D32F2F; color: white; font-weight: bold; font-size: 14px; margin-top: 5px;"
        )
        self.btn_mistakes.clicked.connect(self._start_mistakes)
        settings_layout.addWidget(self.btn_mistakes)

        btn_start = QPushButton("Начать")
        btn_start.setFixedHeight(48)
        btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_start.setStyleSheet(
            "background-color: #217346; color: white; font-weight: bold; font-size: 14px;"
        )
        btn_start.clicked.connect(self._start)
        settings_layout.addWidget(btn_start)

        # Statistics button
        self.btn_stats = QPushButton("📊 Статистика и отчетность")
        self.btn_stats.setFixedHeight(40)
        self.btn_stats.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stats.setStyleSheet(
            "background-color: #4C6EF5; color: white; font-weight: bold; font-size: 13px; margin-top: 10px;"
        )
        self.btn_stats.clicked.connect(self._show_stats)
        layout.addWidget(self.btn_stats)

        layout.addWidget(self.settings_box)
        layout.addStretch()

    def _select_module(self, module):
        exam = load_exam_module(module["id"])
        if not exam:
            QMessageBox.warning(
                self,
                "Нет данных",
                f"Файл тестов для «{module['title']}» не найден.\n"
                "Запустите: python tools/import_exams.py",
            )
            return
        self._module_id = module["id"]
        self._exam_data = exam
        self.settings_box.setEnabled(True)
        self.lbl_selected.setText(module["title"])
        self.ticket_combo.clear()
        for ticket in exam["tickets"]:
            self.ticket_combo.addItem(ticket["title"], ticket["id"])
        self._on_mode_changed()

    def _on_mode_changed(self):
        mode = self.mode_combo.currentData()
        self.ticket_combo.setEnabled(mode == MODE_BY_TICKET)

    def _start(self):
        if not self._module_id:
            return
        mode = self.mode_combo.currentData()
        ticket_id = self.ticket_combo.currentData()
        if mode == MODE_RANDOM:
            ticket_id = random.choice(self._exam_data["tickets"])["id"]
        self.start_session.emit(self._module_id, mode, ticket_id)

    def _start_mistakes(self):
        if not self._module_id:
            return
        self.start_session.emit(self._module_id, MODE_MISTAKES, "mistakes")

    def _show_stats(self):
        dialog = ExamStatsDialog(self)
        dialog.exec()


class ExamSessionWidget(QWidget):
    back_to_hub = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.exam_data = None
        self.mode = MODE_EXAM
        self.ticket = None
        self.q_index = 0
        self.user_answers = {}
        self.is_open_exam = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.btn_back_hub = QPushButton("← К разделам")
        self.btn_back_hub.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back_hub.clicked.connect(self.back_to_hub.emit)
        top.addWidget(self.btn_back_hub)
        top.addStretch()
        self.lbl_header = QLabel("")
        self.lbl_header.setStyleSheet("font-weight: bold; color: #005A9E;")
        top.addWidget(self.lbl_header)
        top.addStretch()
        self.lbl_timer = QLabel("⏱ 00:00")
        self.lbl_timer.setStyleSheet("font-weight: bold; color: #E67700; font-size: 13px; padding: 2px 8px; background: #FFF3BF; border-radius: 4px;")
        top.addWidget(self.lbl_timer)
        layout.addLayout(top)

        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)

        # Dot navigation bar
        self.dots_layout = QHBoxLayout()
        self.dots_layout.setSpacing(4)
        self.dots_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dots_widget = QWidget()
        dots_widget.setLayout(self.dots_layout)
        layout.addWidget(dots_widget)

        # Timer mechanism
        from PyQt6.QtCore import QTimer, QTime
        self.session_timer = QTimer(self)
        self.session_timer.setInterval(1000)
        self.session_timer.timeout.connect(self._update_timer)
        self.elapsed_seconds = 0

        self.stack = QWidget()
        self.stack_layout = QVBoxLayout(self.stack)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        self.question_layout = QVBoxLayout(inner)

        self.lbl_question = QLabel("")
        self.lbl_question.setWordWrap(True)
        self.lbl_question.setStyleSheet(
            "font-size: 14px; font-weight: bold; padding: 8px 0; "
            "background: #F5F9FC; border-radius: 6px; padding: 12px;"
        )
        self.question_layout.addWidget(self.lbl_question)

        self.options_group = QButtonGroup(self)
        self.options_group.setExclusive(True)
        self.options_container = QVBoxLayout()
        self.question_layout.addLayout(self.options_container)

        open_row = QHBoxLayout()
        self.btn_show_answer = QPushButton("Показать ответ")
        self.btn_show_answer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_show_answer.setStyleSheet("background-color: #0078D7; color: white; font-weight: bold;")
        self.btn_show_answer.clicked.connect(self._show_open_answer)
        self.btn_show_answer.hide()
        open_row.addWidget(self.btn_show_answer)

        self.btn_knew = QPushButton("Знал ✓")
        self.btn_knew.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_knew.setStyleSheet("background-color: #217346; color: white; font-weight: bold;")
        self.btn_knew.clicked.connect(lambda: self._mark_open(1))
        self.btn_knew.hide()
        open_row.addWidget(self.btn_knew)

        self.btn_unknown = QPushButton("Не знал ✗")
        self.btn_unknown.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_unknown.setStyleSheet("background-color: #D32F2F; color: white; font-weight: bold;")
        self.btn_unknown.clicked.connect(lambda: self._mark_open(0))
        self.btn_unknown.hide()
        open_row.addWidget(self.btn_unknown)
        self.question_layout.addLayout(open_row)

        self.options_group.buttonClicked.connect(self._on_option_clicked)

        self.lbl_feedback = QLabel("")
        self.lbl_feedback.setWordWrap(True)
        self.lbl_feedback.hide()
        self.lbl_feedback.setStyleSheet(
            "padding: 12px; border-radius: 6px; font-size: 13px; "
            "background: #FAFAFA; border: 1px solid #E0E0E0; line-height: 1.4;"
        )
        self.question_layout.addWidget(self.lbl_feedback)

        self.question_layout.addStretch()
        scroll.setWidget(inner)
        self.stack_layout.addWidget(scroll)
        layout.addWidget(self.stack, stretch=1)

        self.results_panel = QWidget()
        results_layout = QVBoxLayout(self.results_panel)
        self.lbl_score = QLabel("")
        self.lbl_score.setStyleSheet("font-size: 20px; font-weight: bold; color: #217346;")
        self.lbl_score.setAlignment(Qt.AlignmentFlag.AlignCenter)
        results_layout.addWidget(self.lbl_score)
        self.txt_mistakes = QTextEdit()
        self.txt_mistakes.setReadOnly(True)
        results_layout.addWidget(self.txt_mistakes)
        btn_again = QPushButton("Пройти ещё раз")
        btn_again.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_again.clicked.connect(self.back_to_hub.emit)
        results_layout.addWidget(btn_again)
        self.results_panel.hide()
        layout.addWidget(self.results_panel)

        nav = QHBoxLayout()
        self.btn_prev = QPushButton("← Назад")
        self.btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_prev.clicked.connect(self._prev_question)
        self.btn_next = QPushButton("Далее →")
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next.setStyleSheet("background-color: #0078D7; color: white; font-weight: bold;")
        self.btn_next.clicked.connect(self._next_question)
        self.btn_finish = QPushButton("Завершить билет")
        self.btn_finish.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_finish.setStyleSheet("background-color: #217346; color: white; font-weight: bold;")
        self.btn_finish.clicked.connect(self._finish)
        self.btn_finish.hide()
        nav.addWidget(self.btn_prev)
        nav.addStretch()
        nav.addWidget(self.btn_next)
        nav.addWidget(self.btn_finish)
        layout.addLayout(nav)

    def start(self, module_id, mode, ticket_id):
        self.exam_data = load_exam_module(module_id)
        if not self.exam_data:
            QMessageBox.critical(self, "Ошибка", "Не удалось загрузить тесты.")
            self.back_to_hub.emit()
            return

        self.mode = mode
        if ticket_id == "mistakes":
            user_name = CONFIG.get("session_user", "Неизвестный")
            records = load_progress()
            mistake_keys = set()
            for r in records:
                r_user = r.get("user", "Неизвестный")
                if r.get("module_id") == module_id and (r_user == user_name or user_name == "Неизвестный"):
                    for wq in r.get("wrong_questions", []):
                        if isinstance(wq, dict):
                            tid = wq.get("ticket_id")
                            qnum = wq.get("num")
                        else:
                            tid = r.get("ticket_id")
                            qnum = wq
                        if qnum is not None:
                            mistake_keys.add((tid, qnum))

            synthetic_qs = []
            synthetic_answers = []

            for tid, qnum in mistake_keys:
                t = next((t for t in self.exam_data["tickets"] if t["id"] == tid), None)
                if not t:
                    for cand_t in self.exam_data["tickets"]:
                        cand_q = next((q for q in cand_t.get("questions", []) if q["num"] == qnum), None)
                        if cand_q:
                            t = cand_t
                            break

                if t:
                    q = next((q for q in t.get("questions", []) if q["num"] == qnum), None)
                    if q and not any(sq.get("num") == q["num"] and sq.get("text") == q.get("text") for sq in synthetic_qs):
                        synthetic_qs.append(q)
                        answers = t.get("answers") or []
                        q_idx = t["questions"].index(q)
                        if q_idx < len(answers):
                            synthetic_answers.append(answers[q_idx])
                        else:
                            synthetic_answers.append(1)

            if not synthetic_qs:
                QMessageBox.information(
                    self,
                    "Работа над ошибками",
                    "У вас нет нерешенных ошибок в этом модуле! Все тесты пройдены без ошибок."
                )
                self.back_to_hub.emit()
                return

            self.ticket = {
                "id": "mistakes",
                "title": "Мои ошибки",
                "exam_type": self.exam_data.get("exam_type", "test"),
                "questions": synthetic_qs,
                "answers": synthetic_answers,
            }
        else:
            self.ticket = next(
                (t for t in self.exam_data["tickets"] if t["id"] == ticket_id),
                self.exam_data["tickets"][0],
            )
        self.is_open_exam = (
            self.exam_data.get("exam_type") == "open"
            or self.ticket.get("exam_type") == "open"
        )
        self.q_index = 0
        self.user_answers = {}
        self.results_panel.hide()
        self.stack.show()
        self.btn_back_hub.show()
        self.btn_next.show()
        self.btn_finish.hide()

        mode_name = MODE_LABELS.get(mode, mode)
        self.lbl_header.setText(f"{self.exam_data['title']} — {self.ticket['title']} ({mode_name})")
        self.elapsed_seconds = 0
        self.lbl_timer.setText("⏱ 00:00")
        self.session_timer.start()
        self._show_question()

    def _update_timer(self):
        self.elapsed_seconds += 1
        mins = self.elapsed_seconds // 60
        secs = self.elapsed_seconds % 60
        self.lbl_timer.setText(f"⏱ {mins:02d}:{secs:02d}")

    def _update_dots(self):
        # Clear existing dots
        while self.dots_layout.count():
            child = self.dots_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        total = self._total_questions()
        for i in range(total):
            btn = QPushButton(str(i + 1))
            btn.setFixedSize(28, 28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            
            # Styling based on state
            ans = self.user_answers.get(i)
            if i == self.q_index:
                style = "border: 2px solid #3B5BDB; font-weight: bold; background: #E7F5FF; color: #1971C2; border-radius: 14px;"
            elif ans is not None:
                style = "border: 1px solid #2B8A3E; background: #EBFBEE; color: #2B8A3E; border-radius: 14px;"
            else:
                style = "border: 1px solid #CED4DA; background: #FFFFFF; color: #868E96; border-radius: 14px;"
                
            btn.setStyleSheet(f"QPushButton {{ {style} font-size: 10px; }}")
            
            def _jump_to(idx=i):
                self._save_current_answer()
                self.q_index = idx
                self._show_question()
                
            btn.clicked.connect(_jump_to)
            self.dots_layout.addWidget(btn)

    def _total_questions(self):
        return len(self.ticket["questions"])

    def _correct_answer(self, q_idx):
        answers = self.ticket.get("answers") or []
        if q_idx < len(answers):
            return answers[q_idx]
        return 1

    def _is_open_question(self, q):
        return self.is_open_exam or not q.get("options")

    def _show_question(self):
        total = self._total_questions()
        if total == 0:
            return

        q = self.ticket["questions"][self.q_index]
        open_q = self._is_open_question(q)
        self.progress.setMaximum(total)
        self.progress.setValue(self.q_index + 1)
        self.progress.setFormat(f"Вопрос {self.q_index + 1} из {total}")

        self.lbl_question.setText(f"{q['num']}. {q['text']}")

        while self.options_container.count():
            item = self.options_container.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for btn in self.options_group.buttons():
            self.options_group.removeButton(btn)

        self.btn_show_answer.hide()
        self.btn_knew.hide()
        self.btn_unknown.hide()

        if open_q:
            self.btn_show_answer.setVisible(self.mode in (MODE_STUDY, MODE_BY_TICKET, MODE_RANDOM, MODE_EXAM))
            if self.mode != MODE_EXAM:
                self.btn_knew.show()
                self.btn_unknown.show()
            else:
                self.btn_knew.show()
                self.btn_unknown.show()
        else:
            for opt in q["options"]:
                opt_widget = QWidget()
                opt_layout = QHBoxLayout(opt_widget)
                opt_layout.setContentsMargins(4, 4, 4, 4)
                
                rb = QRadioButton()
                rb.setProperty("option_num", opt["num"])
                
                lbl = QLabel(f"{opt['num']}. {opt['text']}")
                lbl.setWordWrap(True)
                lbl.setStyleSheet("font-size: 13px; color: #1A1A1A; line-height: 1.3;")

                # Clicking on label toggles the radio button
                lbl.setCursor(Qt.CursorShape.PointingHandCursor)
                def _make_click_handler(radio=rb):
                    def handler(event):
                        radio.setChecked(True)
                        self._on_option_clicked()
                    return handler
                lbl.mousePressEvent = _make_click_handler(rb)

                opt_layout.addWidget(rb, alignment=Qt.AlignmentFlag.AlignTop)
                opt_layout.addWidget(lbl, stretch=1)
                
                self.options_group.addButton(rb)
                self.options_container.addWidget(opt_widget)

            saved = self.user_answers.get(self.q_index)
            if saved is not None:
                for btn in self.options_group.buttons():
                    if btn.property("option_num") == saved:
                        btn.setChecked(True)
                        break

        self.lbl_feedback.hide()
        if not open_q and self.mode == MODE_STUDY and self.user_answers.get(self.q_index) is not None:
            self._show_study_feedback()

        saved_open = self.user_answers.get(self.q_index)
        if open_q and saved_open is not None and self.mode == MODE_STUDY:
            self._show_open_answer()

        self.btn_prev.setEnabled(self.q_index > 0)
        on_last = self.q_index >= total - 1
        self.btn_next.setVisible(not on_last)
        self.btn_finish.setVisible(on_last)
        self._update_dots()

    def _on_option_clicked(self):
        if self.mode == MODE_STUDY and not self.is_open_exam:
            self._show_study_feedback()

    def _show_open_answer(self):
        q = self.ticket["questions"][self.q_index]
        answer = q.get("answer_text", "Ответ не найден.")
        self.lbl_feedback.setText(f"Ответ:\n\n{answer}")
        self.lbl_feedback.setStyleSheet(
            "padding: 12px; border-radius: 6px; font-size: 13px; "
            "background: #E8F4FD; color: #003D5C; border: 1px solid #B3D9F2;"
        )
        self.lbl_feedback.show()

    def _mark_open(self, value):
        self.user_answers[self.q_index] = value
        total = self._total_questions()
        if self.q_index < total - 1:
            self.q_index += 1
            self._show_question()
        else:
            self._show_results()

    def _selected_option(self):
        btn = self.options_group.checkedButton()
        if btn is None:
            return None
        return btn.property("option_num")

    def _save_current_answer(self):
        sel = self._selected_option()
        if sel is not None:
            self.user_answers[self.q_index] = sel

    def _show_study_feedback(self):
        sel = self._selected_option()
        correct = self._correct_answer(self.q_index)
        q = self.ticket["questions"][self.q_index]
        correct_text = next(
            (o["text"] for o in q["options"] if o["num"] == correct),
            str(correct),
        )
        if sel is None:
            self.lbl_feedback.setText(f"Правильный ответ: {correct}. {correct_text}")
            self.lbl_feedback.setStyleSheet(
                "padding: 10px; border-radius: 5px; background: #E8F4FD; color: #005A9E;"
            )
        elif sel == correct:
            self.lbl_feedback.setText("Верно!")
            self.lbl_feedback.setStyleSheet(
                "padding: 10px; border-radius: 5px; background: #E8F5E9; color: #217346; font-weight: bold;"
            )
        else:
            self.lbl_feedback.setText(f"Неверно. Правильный ответ: {correct}. {correct_text}")
            self.lbl_feedback.setStyleSheet(
                "padding: 10px; border-radius: 5px; background: #FFEBEE; color: #C62828;"
            )
        self.lbl_feedback.show()

    def _prev_question(self):
        self._save_current_answer()
        if self.q_index > 0:
            self.q_index -= 1
            self._show_question()

    def _next_question(self):
        q = self.ticket["questions"][self.q_index]
        if self._is_open_question(q):
            if self.q_index not in self.user_answers and self.mode == MODE_EXAM:
                QMessageBox.warning(self, "Внимание", "Отметьте «Знал» или «Не знал».")
                return
        elif self._selected_option() is None:
            QMessageBox.warning(self, "Внимание", "Выберите вариант ответа.")
            return
        self._save_current_answer()
        if not self._is_open_question(q) and self.mode == MODE_STUDY:
            self._show_study_feedback()
        if self.q_index < self._total_questions() - 1:
            self.q_index += 1
            self._show_question()

    def _finish(self):
        q = self.ticket["questions"][self.q_index]
        if self._is_open_question(q):
            if self.q_index not in self.user_answers:
                QMessageBox.warning(self, "Внимание", "Отметьте «Знал» или «Не знал».")
                return
        elif self._selected_option() is None:
            QMessageBox.warning(self, "Внимание", "Выберите вариант ответа.")
            return
        self._save_current_answer()
        self._show_results()

    def _show_results(self):
        self.session_timer.stop()
        total = self._total_questions()
        wrong_details = []
        lines = []

        for i in range(total):
            q = self.ticket["questions"][i]
            user = self.user_answers.get(i)
            if self._is_open_question(q):
                if user != 1:
                    wrong_details.append({
                        "ticket_id": self.ticket.get("id"),
                        "num": q["num"],
                        "text": q.get("text", "")
                    })
                    status = "не знал" if user == 0 else "—"
                    answer = q.get("answer_text", "")
                    lines.append(
                        f"Вопрос {q['num']}: {status}\n"
                        f"  {q['text']}\n"
                        f"  Ответ: {answer}\n"
                    )
            else:
                correct = self._correct_answer(i)
                if user != correct:
                    wrong_details.append({
                        "ticket_id": self.ticket.get("id"),
                        "num": q["num"],
                        "text": q.get("text", ""),
                        "correct": correct
                    })
                    user_text = next(
                        (o["text"] for o in q.get("options", []) if o["num"] == user),
                        "—",
                    )
                    correct_text = next(
                        (o["text"] for o in q.get("options", []) if o["num"] == correct),
                        str(correct),
                    )
                    lines.append(
                        f"Вопрос {q['num']}: ваш ответ {user} ({user_text})\n"
                        f"  Правильно: {correct} ({correct_text})\n"
                    )

        if self.is_open_exam:
            score = sum(1 for i in range(total) if self.user_answers.get(i) == 1)
        else:
            score = total - len(wrong_details)
        self.lbl_score.setText(f"Результат: {score} из {total}")
        if lines:
            self.txt_mistakes.setText("Ошибки:\n\n" + "\n".join(lines))
        else:
            self.txt_mistakes.setText("Все ответы верны! Отличная работа.")

        if self.mode == MODE_MISTAKES:
            correct_qs = {
                (self.ticket["questions"][i].get("num"), self.ticket["questions"][i].get("text"))
                for i in range(total)
                if (1 if self.is_open_exam else self._correct_answer(i)) == self.user_answers.get(i)
            }
            if correct_qs:
                user_name = CONFIG.get("session_user", "Неизвестный")
                records = load_progress()
                modified = False
                for r in records:
                    r_user = r.get("user", "Неизвестный")
                    if r.get("module_id") == self.exam_data["id"] and (r_user == user_name or user_name == "Неизвестный"):
                        old_wrong = r.get("wrong_questions", [])
                        new_wrong = []
                        for wq in old_wrong:
                            q_num = wq.get("num") if isinstance(wq, dict) else wq
                            q_text = wq.get("text") if isinstance(wq, dict) else None
                            if any(q_num == cq[0] or (q_text and q_text == cq[1]) for cq in correct_qs):
                                modified = True
                            else:
                                new_wrong.append(wq)
                        r["wrong_questions"] = new_wrong
                if modified:
                    save_all_progress(records)

        save_progress_entry({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "user": CONFIG.get("session_user", "Неизвестный"),
            "module_id": self.exam_data["id"],
            "ticket_id": self.ticket["id"],
            "ticket_title": self.ticket["title"],
            "mode": self.mode,
            "score": score,
            "total": total,
            "wrong_questions": wrong_details,
        })

        self.stack.hide()
        self.btn_prev.hide()
        self.btn_next.hide()
        self.btn_finish.hide()
        self.results_panel.show()

        if self.mode == MODE_EXAM:
            QMessageBox.information(self, "Билет завершён", f"Результат: {score} из {total}")


from PyQt6.QtWidgets import QDialog, QTableWidget, QTableWidgetItem, QHeaderView
class ExamStatsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Статистика и отчетность")
        self.resize(700, 500)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        
        user_name = CONFIG.get("session_user", "Неизвестный")
        lbl_title = QLabel(f"Статистика пользователя: {user_name}")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #005A9E;")
        layout.addWidget(lbl_title)

        records = load_progress()
        user_records = [r for r in records if r.get("user", "Неизвестный") == user_name]
        
        if not user_records:
            layout.addWidget(QLabel("У вас пока нет сохраненной статистики."))
            return
            
        total_tests = len(user_records)
        total_qs = sum(r.get("total", 0) for r in user_records)
        total_score = sum(r.get("score", 0) for r in user_records)
        avg_score = (total_score / total_qs * 100) if total_qs > 0 else 0
        
        stats_text = (
            f"Всего пройдено тестов: {total_tests}\n"
            f"Отвечено на вопросов: {total_qs}\n"
            f"Правильных ответов: {total_score} ({avg_score:.1f}%)\n"
        )
        
        lbl_stats = QLabel(stats_text)
        lbl_stats.setStyleSheet("font-size: 14px;")
        layout.addWidget(lbl_stats)

        # Calculate module stats
        module_stats = {}
        for r in user_records:
            mid = r.get("module_id", "unknown")
            if mid not in module_stats:
                module_stats[mid] = {"total": 0, "wrong": set()}
            module_stats[mid]["total"] += 1
            for wq in r.get("wrong_questions", []):
                qnum = wq.get("num") if isinstance(wq, dict) else wq
                tid = wq.get("ticket_id") if isinstance(wq, dict) else r.get("ticket_id")
                module_stats[mid]["wrong"].add((tid, qnum))
                
        recommendations = []
        for mid, st in module_stats.items():
            mod_title = next((m["title"] for m in EXAM_MODULES if m["id"] == mid), mid)
            wrong_count = len(st["wrong"])
            if wrong_count > 0:
                recommendations.append(f"• В модуле «{mod_title}» у вас {wrong_count} нерешенных ошибок. Рекомендуется запустить «Работа над ошибками».")
            elif st["total"] > 0:
                recommendations.append(f"• В модуле «{mod_title}» у вас нет ошибок! Вы отлично справляетесь.")
                
        if not recommendations:
            recommendations.append("Продолжайте решать тесты для сбора статистики.")
            
        group_rec = QGroupBox("Рекомендации (ИИ)")
        group_rec.setStyleSheet("font-weight: bold; color: #333;")
        rec_layout = QVBoxLayout(group_rec)
        lbl_rec = QLabel("\n".join(recommendations))
        lbl_rec.setWordWrap(True)
        lbl_rec.setStyleSheet("font-weight: normal; font-size: 13px; color: #217346;")
        rec_layout.addWidget(lbl_rec)
        layout.addWidget(group_rec)
        
        # Details table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Дата", "Модуль", "Билет / Режим", "Результат"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setRowCount(len(user_records))
        
        for i, r in enumerate(reversed(user_records)):
            self.table.setItem(i, 0, QTableWidgetItem(r.get("date", "")))
            mod_title = next((m["title"] for m in EXAM_MODULES if m["id"] == r.get("module_id")), r.get("module_id", ""))
            self.table.setItem(i, 1, QTableWidgetItem(mod_title))
            mode_lbl = MODE_LABELS.get(r.get("mode"), r.get("mode", ""))
            self.table.setItem(i, 2, QTableWidgetItem(f"{r.get('ticket_title', '')} ({mode_lbl})"))
            score_str = f"{r.get('score', 0)} / {r.get('total', 0)}"
            self.table.setItem(i, 3, QTableWidgetItem(score_str))
            
        layout.addWidget(self.table)
        
        btn_close = QPushButton("Закрыть")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
