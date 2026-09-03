import os
import tempfile
import openpyxl
from openpyxl.styles import Font, Border, Side, Alignment, PatternFill
from datetime import datetime
from checklist_db import get_task_items
from printer_utils import print_files_batch

def create_and_print_checklist(task_id, executor, workshop_name, location_name, note, printer_name=None):
    task_data = get_task_items(task_id)
    items = task_data['items']
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Чеклист"
    
    # Page setup
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = False
    ws.page_margins.left = 0.5
    ws.page_margins.right = 0.5
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.5
    
    # Fonts and borders
    font_bold = Font(name='Arial', size=12, bold=True)
    font_normal = Font(name='Arial', size=11)
    font_small = Font(name='Arial', size=10)
    font_title = Font(name='Arial', size=14, bold=True)
    
    thin = Side(border_style="thin", color="000000")
    border_all = Border(top=thin, left=thin, right=thin, bottom=thin)
    
    # Header
    ws.merge_cells('A1:C1')
    ws['A1'] = "ЗАДАНИЕ НА ЗАМЕНУ ПРИБОРОВ"
    ws['A1'].font = font_title
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
    
    ws.merge_cells('A2:C2')
    ws['A2'] = f"Дата: {datetime.now().strftime('%d.%m.%Y')}    Исполнитель: {executor}"
    ws['A2'].font = font_normal
    ws['A2'].alignment = Alignment(horizontal='center', vertical='center')
    
    ws.merge_cells('A3:C3')
    ws['A3'] = f"Объект: {workshop_name} — {location_name}"
    ws['A3'].font = font_bold
    ws['A3'].alignment = Alignment(horizontal='center', vertical='center')
    
    if note:
        ws.merge_cells('A4:C4')
        ws['A4'] = f"Примечание: {note}"
        ws['A4'].font = font_normal
        ws['A4'].alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
        start_row = 6
    else:
        start_row = 5
        
    # Table headers
    headers = ["Позиция", "Снять (есть)", "Поставить (№ _____ Пов.до)"]
    for col_idx, text in enumerate(headers, start=1):
        cell = ws.cell(row=start_row, column=col_idx, value=text)
        cell.font = font_bold
        cell.border = border_all
        cell.fill = PatternFill(start_color="EEEEEE", end_color="EEEEEE", fill_type="solid")
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        
    ws.column_dimensions['A'].width = 30
    ws.column_dimensions['B'].width = 25
    ws.column_dimensions['C'].width = 35
    
    current_row = start_row + 1
    
    for item in items:
        # Col A: Position
        c_a = ws.cell(row=current_row, column=1, value=item['position'])
        c_a.font = font_normal
        c_a.border = border_all
        c_a.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
        
        # Col B: Removed
        removed_text = "[ПУСТО]"
        if item['removed_device_id']:
            removed_text = f"{item['removed_name']}\n№ {item['removed_serial'] or 'нет'}"
            
        c_b = ws.cell(row=current_row, column=2, value=removed_text)
        c_b.font = font_small
        c_b.border = border_all
        c_b.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        
        # Col C: Installed (empty for writing)
        c_c = ws.cell(row=current_row, column=3, value="")
        c_c.border = border_all
        
        ws.row_dimensions[current_row].height = 45
        current_row += 1
        
    current_row += 2
    ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=3)
    c_sign = ws.cell(row=current_row, column=1, value="Подпись: ______________________")
    c_sign.font = font_normal
    c_sign.alignment = Alignment(horizontal='right')
    
    # Save to temp
    fd, temp_path = tempfile.mkstemp(suffix=".xlsx", prefix="Checklist_")
    os.close(fd)
    wb.save(temp_path)
    
    # Print
    print_files_batch([temp_path], printer_name=printer_name)
    
    try:
        os.remove(temp_path)
    except:
        pass
    
    return True
