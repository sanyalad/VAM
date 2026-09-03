"""Parse exam banks from Word documents into JSON-serializable structures."""

import json
import os
import re
from pathlib import Path

from docx import Document

TICKET_MARKERS = (
    re.compile(r"^[Тт]ест\s*[№#]?\s*(\d+)\s*$"),
    re.compile(r"^[Бб]илет\s*[№#]?\s*(\d+)\s*$"),
)


def _parse_answer_key_table(doc):
    if not doc.tables:
        return {}
    key = {}
    for row in doc.tables[0].rows[1:]:
        cells = [c.text.strip().replace("\n", " ") for c in row.cells]
        if not cells:
            continue
        m = re.search(r"(\d+)", cells[0])
        if not m:
            continue
        tid = int(m.group(1))
        answers = [int(x) for x in cells[1:11] if x.isdigit()]
        if len(answers) == 10:
            key[tid] = answers
    return key


def _is_question_line(qtext):
    words = [w for w in re.findall(r"[а-яА-Яa-zA-Z]+", qtext) if len(w) > 1]
    uppercase_words = [w for w in words if w.isupper()]
    return len(uppercase_words) >= 2 or qtext.endswith("?") or qtext.isupper()


def _parse_questions_from_lines(lines, ticket_label="Тест"):
    tests = {}
    cur_tid = None
    cur_q = None
    state = "INIT"  # INIT, QUESTION, OPTIONS

    for line in lines:
        line = line.strip()
        if not line:
            continue

        ticket_found = None
        for pat in TICKET_MARKERS:
            m = pat.match(line)
            if m:
                ticket_found = int(m.group(1))
                break
        if ticket_found is not None:
            cur_tid = ticket_found
            tests.setdefault(cur_tid, [])
            cur_q = None
            state = "INIT"
            continue

        if cur_tid is None:
            continue

        qs = tests[cur_tid]
        target_q_num = len(qs) + 1

        m_q = re.match(r"^" + str(target_q_num) + r"\.\s*(.*)", line)
        is_q = False
        if m_q and state != "QUESTION":
            qtext = m_q.group(1).strip()
            if _is_question_line(qtext):
                is_q = True

        if is_q:
            cur_q = {"num": target_q_num, "text": m_q.group(1).strip(), "options": []}
            qs.append(cur_q)
            state = "QUESTION"
            continue

        if state == "QUESTION":
            m_opt1 = re.match(r"^1\.\s*(.*)", line)
            if m_opt1:
                cur_q["options"].append({"num": 1, "text": m_opt1.group(1).strip()})
                state = "OPTIONS"
            elif cur_q:
                cur_q["text"] = (cur_q["text"] + " " + line).strip()
            continue

        if state == "OPTIONS":
            target_opt_num = len(cur_q["options"]) + 1
            m_opt = re.match(r"^" + str(target_opt_num) + r"\.\s*(.*)", line)
            if m_opt:
                cur_q["options"].append({"num": target_opt_num, "text": m_opt.group(1).strip()})
            elif cur_q and cur_q["options"]:
                cur_q["options"][-1]["text"] = (cur_q["options"][-1]["text"] + " " + line).strip()

    return tests


def _parse_questions_from_docx(doc):
    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return _parse_questions_from_lines(lines)


def _build_exam_payload(exam_id, title, key, tests, ticket_label="Тест"):
    tickets = []
    for tid in sorted(tests):
        questions = tests[tid]
        if not questions:
            continue
        answers = key.get(tid)
        if answers is None and questions:
            answers = [1] * len(questions)
        tickets.append({
            "id": tid,
            "title": f"{ticket_label} № {tid}",
            "answers": answers or [],
            "questions": questions,
        })
    return {"id": exam_id, "title": title, "tickets": tickets}


def parse_docx_exam(path, exam_id, title, ticket_label="Тест"):
    try:
        doc = Document(path)
        key = _parse_answer_key_table(doc)
        tests = _parse_questions_from_docx(doc)
        return _build_exam_payload(exam_id, title, key, tests, ticket_label)
    except Exception as e:
        raise ValueError(f"Не удалось прочитать docx-файл {os.path.basename(path)}: {e}")


def read_doc_text_word_com(path):
    com_ok = False
    try:
        import pythoncom
        pythoncom.CoInitialize()
        com_ok = True
    except Exception:
        pass

    word = None
    doc = None
    try:
        import win32com.client
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        try:
            word.DisplayAlerts = 0
        except Exception:
            pass
        doc = word.Documents.Open(os.path.abspath(path))
        text = doc.Content.Text
        return text
    except Exception as e:
        raise ValueError(f"Не удалось открыть файл в Word: {e}")
    finally:
        try:
            if doc is not None:
                doc.Close(False)
        except Exception:
            pass
        doc = None
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
            word = None
        import gc
        gc.collect()
        if com_ok:
            try:
                import pythoncom
                # pythoncom.CoUninitialize()
                pass
            except Exception:
                pass


def _clean_ptb_text(text):
    if not text:
        return ""
    text = text.replace("\u0007", "\n")
    text = text.replace("\t", " ")
    text = text.replace("\r", "\n")

    fixes = (
        ("злектробезопасности", "электробезопасности"),
        ("Злектробезопасности", "Электробезопасности"),
        ("электробеэопасности", "электробезопасности"),
        ("Знаний настоящих", "знаний настоящих"),
        ("действующий электроустановки", "действующие электроустановки"),
        ("1000 в.", "1000 В."),
        ("1000В", "1000 В"),
        ("1000 в", "1000 В"),
        ("220 кВ", "220 кВ"),
        ("IV. остальные", "IV, остальные"),
        ("в наряда.", "в наряде."),
        ("ГРУППОЙ I", "группой I"),
        ("0 перерывов", "10. Перерывы"),
    )
    for old, new in fixes:
        text = text.replace(old, new)

    if "Напряжение, кВ" in text and "Расстояние от человека" in text:
        before = text.split("Напряжение, кВ")[0].strip()
        table = (
            "Допустимые расстояния (таблица ПТБ):\n"
            "• до 1 кВ — на ВЛ: 0,6 м; на прочих ЭУ: без прикосновения; "
            "от механизмов и грузов: 1,0 м\n"
            "• 6–35 кВ: 0,6 м / 1,0 м\n"
            "• 110 кВ: 1,0 м / 1,5 м\n"
            "• 150 кВ: 1,5 м / 2,0 м\n"
            "• 220 кВ: 2,0 м / 2,5 м"
        )
        after = ""
        if "и не требуется принятия" in text:
            after = text.split("и не требуется принятия", 1)[-1].strip()
            after = "И не требуется принятия " + after if after else ""
        text = before
        if before:
            text += "\n\n"
        text += table
        if after:
            text += "\n\n" + after

    if "Таблица 3.2" in text or "Совмещение обязанностей" in text:
        text = re.sub(
            r"Таблица 3\.2.*?(?=Наряд на работу|$)",
            (
                "Таблица 3.2 — совмещение обязанностей:\n"
                "• Выдающий наряд — может быть руководителем работ и допускающим "
                "(в ЭУ без местных дежурных)\n"
                "• Допускающий — может готовить рабочее место, быть руководителем "
                "работ и членом бригады\n"
                "• Руководитель работ — может быть допускающим "
                "(в ЭУ без местных дежурных)\n"
                "При совмещении группа по электробезопасности не ниже требуемой "
                "для каждой роли."
            ),
            text,
            flags=re.DOTALL,
        )

    lines = []
    for raw in text.split("\n"):
        line = re.sub(r" +", " ", raw.strip())
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if line.startswith("- ") or line.startswith("-"):
            line = "• " + line.lstrip("-– ").strip()
        elif re.match(r"^\d+\)\s", line):
            line = "• " + line
        lines.append(line)

    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _fix_ptb_orphans(questions):
    fixed = []
    for q in questions:
        t = q.get("text", "").strip()
        if not q.get("answer_text") and fixed:
            prev = fixed[-1]
            if t and (
                t[0].islower()
                or t.startswith("перерыв")
                or "окончание" in t.lower()
            ):
                prev["answer_text"] = f"{prev['answer_text']}\n• {t[0].upper() + t[1:]}"
                continue
        fixed.append(q)
    return fixed


def _format_ptb_lists(text):
    if not text or "являются:" not in text:
        return text
    head, rest = text.split("являются:", 1)
    parts = re.split(r";\s*\n?", rest)
    items = [p.strip(" ;\n") for p in parts if p.strip(" ;\n")]
    if len(items) >= 3:
        bullets = "\n".join(f"• {it[0].upper() + it[1:] if it else it}" for it in items)
        return f"{head}являются:\n{bullets}"
    return text


def _finalize_ptb_question(q):
    q["text"] = _clean_ptb_text(q.get("text", ""))
    q["answer_text"] = _format_ptb_lists(_clean_ptb_text(q.get("answer_text", "")))
    if not q["text"] and q["answer_text"]:
        q["text"] = q["answer_text"][:120] + ("…" if len(q["answer_text"]) > 120 else "")
    return q


def _merge_ptb_duplicates(questions):
    merged = []
    for q in questions:
        q = _finalize_ptb_question(q)
        if (
            merged
            and not merged[-1]["answer_text"]
            and merged[-1]["num"] == q["num"]
        ):
            merged[-1]["answer_text"] = q["text"] if not q["answer_text"] else q["answer_text"]
            if q["text"] and not q["answer_text"]:
                pass
            elif q["answer_text"]:
                merged[-1]["answer_text"] = q["answer_text"]
            continue
        if (
            merged
            and not merged[-1]["answer_text"]
            and q["answer_text"]
            and len(q["text"]) < 80
            and "определение" in merged[-1]["text"].lower()
        ):
            merged[-1]["answer_text"] = q["answer_text"] or q["text"]
            continue
        merged.append(q)
    return merged


def parse_ptb_doc_exam(path, exam_id, title, questions_per_ticket=10):
    """ПТБ: нумерованные вопросы с текстовыми ответами (без вариантов выбора)."""
    text = read_doc_text_word_com(path)
    lines = [l.strip() for l in re.split(r"[\r\n]+", text) if l.strip()]

    questions = []
    cur = None

    def flush():
        nonlocal cur
        if cur:
            questions.append(cur)
            cur = None

    for line in lines:
        if line.startswith("Билеты"):
            continue

        m_dot = re.match(r"^(\d+)\.\s*(.*)", line)
        m_space = re.match(r"^(\d+)\s+(.+)", line)

        if m_dot:
            num = int(m_dot.group(1))
            rest = m_dot.group(2).strip()
            if cur and cur["num"] == num and not cur["answer_text"]:
                if rest:
                    cur["text"] = f"{cur['text']} {rest}".strip()
                continue
            flush()
            cur = {
                "num": num,
                "text": rest or f"Вопрос {num}",
                "answer_text": "",
                "options": [],
            }
        elif m_space and cur and int(m_space.group(1)) == cur["num"]:
            part = m_space.group(2).strip()
            cur["answer_text"] = (
                f"{cur['answer_text']}\n{part}" if cur["answer_text"] else part
            )
        elif m_space:
            num = int(m_space.group(1))
            rest = m_space.group(2).strip()
            flush()
            cur = {
                "num": num,
                "text": rest,
                "answer_text": "",
                "options": [],
            }
        elif cur is not None:
            cur["answer_text"] = (
                f"{cur['answer_text']}\n{line}" if cur["answer_text"] else line
            )

    flush()
    questions = _merge_ptb_duplicates(questions)
    questions = _fix_ptb_orphans(questions)
    questions = [_finalize_ptb_question(q) for q in questions if q.get("text") or q.get("answer_text")]

    tickets = []
    for i in range(0, len(questions), questions_per_ticket):
        chunk = questions[i : i + questions_per_ticket]
        tid = i // questions_per_ticket + 1
        for j, q in enumerate(chunk, start=1):
            q["num"] = j
        tickets.append({
            "id": tid,
            "title": f"Билет № {tid}",
            "answers": [],
            "exam_type": "open",
            "questions": chunk,
        })

    return {
        "id": exam_id,
        "title": title,
        "exam_type": "open",
        "tickets": tickets,
    }


def parse_doc_exam(path, exam_id, title, ticket_label="Билет"):
    text = read_doc_text_word_com(path)
    lines = [l.strip() for l in re.split(r"[\r\n]+", text) if l.strip()]
    tests = _parse_questions_from_lines(lines, ticket_label=ticket_label)
    key = {}
    for tid, questions in tests.items():
        if questions:
            key[tid] = [1] * len(questions)
    return _build_exam_payload(exam_id, title, key, tests, ticket_label)


def save_exam_json(payload, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return out_path


def validate_exam_payload(payload):
    issues = []
    is_open = payload.get("exam_type") == "open"
    for ticket in payload.get("tickets", []):
        q_count = len(ticket.get("questions", []))
        a_count = len(ticket.get("answers", []))
        if q_count == 0:
            issues.append(f"{ticket.get('title')}: нет вопросов")
        if not is_open:
            if q_count != 10:
                issues.append(f"{ticket.get('title')}: вопросов {q_count} вместо 10")
            if a_count and a_count != q_count:
                issues.append(f"{ticket.get('title')}: ответов {a_count}, вопросов {q_count}")
        for q in ticket.get("questions", []):
            opts = q.get("options", [])
            if not is_open:
                if len(opts) < 2:
                    issues.append(f"{ticket.get('title')} в.{q.get('num')}: вариантов {len(opts)} (менее 2)")
            if is_open and not q.get("answer_text"):
                issues.append(f"{ticket.get('title')} в.{q.get('num')}: нет текста ответа")
        if not is_open and ticket.get("answers"):
            answers = ticket["answers"]
            questions = ticket.get("questions", [])
            for idx, q in enumerate(questions):
                if idx < len(answers):
                    ans_val = answers[idx]
                    opt_nums = [o["num"] for o in q.get("options", [])]
                    if opt_nums and ans_val not in opt_nums:
                        issues.append(f"{ticket.get('title')} в.{q.get('num')}: верный ответ {ans_val} отсутствует в вариантах {opt_nums}")
    return issues
