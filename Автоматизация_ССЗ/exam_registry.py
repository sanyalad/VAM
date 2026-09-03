import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "exams"
PROGRESS_FILE = BASE_DIR / "exam_progress.json"

EXAM_MODULES = [
    {
        "id": "eb_group3",
        "title": "Тесты на III группу",
        "subtitle": "Экзаменационные билеты с вариантами ответов — 30 × 10 вопросов",
        "data_file": "eb_group3.json",
        "enabled": True,
    },
    {
        "id": "eb_ptb",
        "title": "Билеты ПТБ",
        "subtitle": "Правила безопасной эксплуатации ЭУ — заучивание с самопроверкой",
        "data_file": "eb_ptb.json",
        "enabled": True,
    },
]


def load_exam_module(module_id):
    module = next((m for m in EXAM_MODULES if m["id"] == module_id), None)
    if not module or not module.get("enabled") or not module.get("data_file"):
        return None
    path = DATA_DIR / module["data_file"]
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data["_module"] = module
    return data


def load_progress():
    if not PROGRESS_FILE.exists():
        return []
    try:
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_progress_entry(entry):
    records = load_progress()
    records.append(entry)
    save_all_progress(records)

def save_all_progress(records):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
