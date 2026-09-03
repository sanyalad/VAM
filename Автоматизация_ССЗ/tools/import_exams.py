"""Import exam banks from source Word files into data/exams/*.json"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from exam_parser import (
    parse_docx_exam,
    parse_ptb_doc_exam,
    save_exam_json,
    validate_exam_payload,
)

SOURCES = {
    "eb_group3": {
        "paths": [
            r"E:\Электробезопасность\тесты на 3 группу по ЭБ.docx",
            str(ROOT / "data" / "exams" / "тесты на 3 группу по ЭБ.docx"),
            str(ROOT / "тесты на 3 группу по ЭБ.docx"),
        ],
        "title": "Электробезопасность — группа III",
        "ticket_label": "Тест",
        "parser": "docx",
    },
    "eb_ptb": {
        "paths": [
            r"E:\Электробезопасность\ПТБ билеты .doc",
            str(ROOT / "data" / "exams" / "ПТБ билеты .doc"),
            str(ROOT / "ПТБ билеты .doc"),
        ],
        "title": "ПТБ — билеты",
        "ticket_label": "Билет",
        "parser": "ptb",
    },
}


def find_existing_path(candidates):
    for c in candidates:
        p = Path(c)
        if p.exists():
            return p
    return None


def main():
    out_dir = ROOT / "data" / "exams"
    ok = True

    for exam_id, cfg in SOURCES.items():
        src = find_existing_path(cfg["paths"])
        if not src:
            print(f"[SKIP] {exam_id}: файл не найден среди путей: {cfg['paths']}")
            ok = False
            continue

        print(f"Импорт {exam_id} из {src.name}...")
        if cfg["parser"] == "docx":
            payload = parse_docx_exam(
                str(src), exam_id, cfg["title"], ticket_label=cfg["ticket_label"]
            )
        elif cfg["parser"] == "ptb":
            payload = parse_ptb_doc_exam(str(src), exam_id, cfg["title"])
        else:
            payload = parse_ptb_doc_exam(str(src), exam_id, cfg["title"])

        issues = validate_exam_payload(payload)
        out_path = save_exam_json(payload, out_dir / f"{exam_id}.json")
        tickets = len(payload["tickets"])
        questions = sum(len(t["questions"]) for t in payload["tickets"])
        print(f"  -> {out_path.name}: {tickets} билетов, {questions} вопросов")
        if issues:
            print(f"  Предупреждения ({len(issues)}):")
            for issue in issues[:10]:
                print(f"    - {issue}")
            if len(issues) > 10:
                print(f"    ... и ещё {len(issues) - 10}")

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
