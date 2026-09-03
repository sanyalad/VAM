import sys
import json
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent

def test_json_payloads():
    from exam_parser import validate_exam_payload
    
    eb3_path = ROOT / "data" / "exams" / "eb_group3.json"
    ptb_path = ROOT / "data" / "exams" / "eb_ptb.json"

    assert eb3_path.exists(), f"Missing {eb3_path}"
    assert ptb_path.exists(), f"Missing {ptb_path}"

    with open(eb3_path, encoding='utf-8') as f:
        eb3 = json.load(f)

    with open(ptb_path, encoding='utf-8') as f:
        ptb = json.load(f)

    issues3 = validate_exam_payload(eb3)
    assert len(issues3) == 0, f"eb_group3 has issues: {issues3}"
    assert len(eb3["tickets"]) == 30, f"Expected 30 tickets, got {len(eb3['tickets'])}"
    for t in eb3["tickets"]:
        assert len(t["questions"]) == 10, f"Ticket {t['id']} has {len(t['questions'])} questions"
        for q in t["questions"]:
            assert len(q["options"]) >= 2, f"Ticket {t['id']} Q{q['num']} has < 2 options"

    issues_ptb = validate_exam_payload(ptb)
    assert len(issues_ptb) == 0, f"eb_ptb has issues: {issues_ptb}"
    assert len(ptb["tickets"]) > 0, "eb_ptb has no tickets"

    print("ALL DATASET TESTS PASSED SUCCESSFULLY!")

def test_trainer_ui_headless():
    from PyQt6.QtWidgets import QApplication
    from exam_trainer import ExamHubWidget, ExamSessionWidget

    app = QApplication.instance() or QApplication(sys.argv)

    hub = ExamHubWidget()
    assert hub is not None

    session = ExamSessionWidget()
    session.start("eb_group3", "by_ticket", 1)
    assert session.ticket is not None
    assert len(session.ticket["questions"]) == 10

    # Simulate next question and study mode feedback
    session.mode = "study"
    session._show_question()
    session._on_option_clicked()

    print("ALL UI HEADLESS TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_json_payloads()
    test_trainer_ui_headless()
