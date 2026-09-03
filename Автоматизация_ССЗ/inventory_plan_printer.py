"""Отдельный печатный лист ежедневного плана уточнения базы приборов."""

from html import escape

from PyQt6.QtCore import QMarginsF
from PyQt6.QtGui import QPageLayout, QPageSize, QTextDocument
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
from PyQt6.QtWidgets import QDialog


PRIORITY_LABELS = {
    "critical": "Критично",
    "high": "Нужны данные",
    "medium": "Запланировать",
}


def build_daily_plan_html(plan_date, tasks):
    """Формирует компактный A4-лист, удобный для записей непосредственно в цехе."""
    rows = []
    for number, task in enumerate(tasks, 1):
        device = escape(str(task.get("device_name") or "Прибор не указан"))
        serial = escape(str(task.get("serial_number") or "не указан"))
        work = str(task.get("work") or "")
        # На листе прибор уже указан в отдельной колонке — убираем повтор из задания.
        if ":" in work:
            work = work.split(":", 1)[1].strip()
        rows.append(
            "<tr>"
            f"<td class='num'>{number}</td>"
            f"<td class='priority'>{escape(PRIORITY_LABELS.get(task.get('priority'), str(task.get('priority') or 'Обычный')))}</td>"
            f"<td><b>{device}</b><br>Зав. № {serial}</td>"
            f"<td>{escape(str(task.get('place') or 'Место уточнить'))}</td>"
            f"<td>{escape(work).replace(chr(10), '<br>')}</td>"
            "<td class='result'>□ выполнено &nbsp; □ нужны данные<br><br>Прим.: ______________</td>"
            "</tr>"
        )
    date_text = plan_date.strftime("%d.%m.%Y")
    workshop = escape(str(tasks[0].get("workshop_name") or "Цех не указан")) if tasks else "—"
    return f"""
    <html><head><meta charset='utf-8'><style>
      body {{ font-family: Arial, sans-serif; color: #111827; font-size: 7.5pt; }}
      h1 {{ text-align: center; font-size: 13pt; margin: 0 0 3px 0; }}
      .meta {{ text-align: center; font-size: 9pt; margin-bottom: 6px; }}
      table {{ width: 100%; border-collapse: collapse; }}
      th {{ background: #E5E7EB; font-weight: bold; text-align: center; }}
      th, td {{ border: 1px solid #374151; padding: 3px; vertical-align: top; }}
      .num {{ width: 4%; text-align: center; }}
      .priority {{ width: 10%; text-align: center; }}
      .result {{ width: 16%; white-space: nowrap; }}
      .footer {{ margin-top: 7px; font-size: 9pt; }}
    </style></head><body>
      <h1>ПЛАН УТОЧНЕНИЯ БАЗЫ ПРИБОРОВ</h1>
      <div class='meta'>Дата: <b>{date_text}</b> &nbsp;&nbsp; Цех: <b>{workshop}</b> &nbsp;&nbsp; Приборов: <b>{len(tasks)}</b></div>
      <table>
        <tr><th>№</th><th>Приоритет</th><th>Прибор</th><th>Место</th><th>Что выяснить / сделать</th><th>Результат</th></tr>
        {''.join(rows)}
      </table>
      <div class='footer'>Исполнитель: ____________________ &nbsp;&nbsp;&nbsp; Подпись: ____________________</div>
    </body></html>
    """


def _make_printer():
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    printer.setPageMargins(QMarginsF(8, 8, 8, 8), QPageLayout.Unit.Millimeter)
    return printer


def _make_document(plan_date, tasks):
    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setHtml(build_daily_plan_html(plan_date, tasks))
    return document


def preview_daily_plan(parent, plan_date, tasks):
    printer = _make_printer()
    document = _make_document(plan_date, tasks)
    dialog = QPrintPreviewDialog(printer, parent)
    dialog.setWindowTitle(f"Предпросмотр плана на {plan_date.strftime('%d.%m.%Y')}")
    dialog.resize(1100, 760)
    dialog.paintRequested.connect(document.print)
    dialog.exec()


def print_daily_plan(parent, plan_date, tasks):
    printer = _make_printer()
    dialog = QPrintDialog(printer, parent)
    dialog.setWindowTitle(f"Печать плана на {plan_date.strftime('%d.%m.%Y')}")
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    _make_document(plan_date, tasks).print(printer)
    return True
