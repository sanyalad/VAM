import traceback
from openpyxl import load_workbook
try:
    wb = load_workbook('Шаблон_ССЗ.xlsx')
    ws = wb.active
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    wb.save('test.xlsx')
    print('OK')
except Exception as e:
    traceback.print_exc()
