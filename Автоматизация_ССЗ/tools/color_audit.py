"""Сверка закрашенных ячеек между .xls и .xlsx."""



import os

import sys



_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if _ROOT not in sys.path:

    sys.path.insert(0, _ROOT)



from operations_log import log_audit

from ssz_schedule import (

    AnalysisReport,

    get_schedules_dir,

    fetch_month_schedules,

    _fetch_one_file_colored,

    normalize_work_text,

    schedules_need_com_excel,

)

from xls_color_cache import ExcelColorSession





def _colored_keys(colored_list):

    return {

        (p["day"], p["month"], p["place"], normalize_work_text(p["work"]))

        for p in colored_list

    }





def _report_color_lines(report, prefix=""):

    s = report.stats

    lines = []

    if prefix:

        lines.append(prefix)

    lines.append(report.stats_summary())

    lines.append(

        f"  openpyxl_colored={s.get('openpyxl_colored', 0)} "

        f"com_colored_added={s.get('com_colored_added', 0)} "

        f"com_cells={s.get('com_cells', 0)}"

    )

    return lines





def compare_schedules_dir(month=6):

    """Сверка текущей папки Графики (как в приложении)."""

    completed = set()

    report = AnalysisReport()



    if schedules_need_com_excel():

        with ExcelColorSession() as session:

            _, colored, _ = fetch_month_schedules(

                month, completed, report=report, color_session=session

            )

    else:

        _, colored, _ = fetch_month_schedules(

            month, completed, report=report, color_session=None

        )

    lines = [

        f"month={month}",

        f"schedules_need_com_excel={schedules_need_com_excel()}",

        *_report_color_lines(report),

        f"colored_skipped total={len(colored)}",

    ]

    log_audit(lines)

    print("\n".join(lines))

    return lines





def compare_pair(xls_path, xlsx_path, month=6):

    """Сверка двух файлов по абсолютным путям (не трогает папку Графики)."""

    completed = set()

    report_xls = AnalysisReport()

    with ExcelColorSession() as session:

        colored_xls = _fetch_one_file_colored(

            os.path.abspath(xls_path),

            month,

            completed,

            color_session=session,

            report=report_xls,

        )

    report_xlsx = AnalysisReport()

    if schedules_need_com_excel():

        with ExcelColorSession() as session:

            colored_xlsx = _fetch_one_file_colored(

                os.path.abspath(xlsx_path),

                month,

                completed,

                color_session=session,

                report=report_xlsx,

            )

    else:

        colored_xlsx = _fetch_one_file_colored(

            os.path.abspath(xlsx_path),

            month,

            completed,

            color_session=None,

            report=report_xlsx,

        )



    set_xls = _colored_keys(colored_xls)

    set_xlsx = _colored_keys(colored_xlsx)

    only_xls = set_xls - set_xlsx

    only_xlsx = set_xlsx - set_xls



    lines = [

        f"xls: {xls_path}",

        f"xlsx: {xlsx_path}",

        f"month={month}",

        *_report_color_lines(report_xls, "xls report:"),

        *_report_color_lines(report_xlsx, "xlsx report:"),

        f"xls colored={len(set_xls)} xlsx colored={len(set_xlsx)}",

        f"only in xls: {len(only_xls)}",

        f"only in xlsx: {len(only_xlsx)}",

    ]

    for k in sorted(only_xls)[:30]:

        lines.append(f"  - xls only: [{k[0]:02d}.{k[1]:02d}] {k[2]}: {k[3][:60]}")

    for k in sorted(only_xlsx)[:30]:

        lines.append(f"  + xlsx only: [{k[0]:02d}.{k[1]:02d}] {k[2]}: {k[3][:60]}")

    log_audit(lines)

    print("\n".join(lines))

    print("\nПолный отчёт дописан в color_audit.txt")

    return lines





if __name__ == "__main__":

    if len(sys.argv) >= 3:

        m = int(sys.argv[3]) if len(sys.argv) > 3 else 6

        compare_pair(sys.argv[1], sys.argv[2], m)

    elif os.path.isdir(get_schedules_dir()):

        m = int(sys.argv[1]) if len(sys.argv) > 1 else 6

        compare_schedules_dir(m)

    else:

        print("Usage: python tools/color_audit.py [month]")

        print("   or: python tools/color_audit.py file.xls file.xlsx [month]")

