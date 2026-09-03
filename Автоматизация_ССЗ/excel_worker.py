import sys
import json
import os

from ppr_color_service import ColorBatchResult, ColorState, decide_excel_color

def check_cells_worker(fpath, cells_list, use_display):
    import pythoncom
    import win32com.client
    
    pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
    
    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    excel.ScreenUpdating = False
    try:
        excel.Interactive = False
        excel.AutomationSecurity = 3
    except Exception:
        pass
        
    result = ColorBatchResult()
    wb = None
    try:
        wb = excel.Workbooks.Open(
            fpath, UpdateLinks=0, ReadOnly=True, IgnoreReadOnlyRecommended=True
        )
        sheet_map = {str(ws.Name): ws for ws in wb.Worksheets}
        
        from collections import defaultdict
        by_sheet = defaultdict(list)
        for sheet_name, row, col in cells_list:
            by_sheet[sheet_name].append((row, col))
            
        def read_row(ws, row, cols):
            if not cols: return {}
            min_c, max_c = min(cols), max(cols)
            res = {}
            try:
                if min_c == max_c:
                    color = ws.Cells(int(row)+1, int(min_c)+1).Interior.Color
                    if color is not None: res[(row, min_c)] = int(color)
                else:
                    rng = ws.Range(ws.Cells(int(row)+1, int(min_c)+1), ws.Cells(int(row)+1, int(max_c)+1))
                    colors = rng.Interior.Color
                    if isinstance(colors, (int, float)):
                        for c in range(min_c, max_c+1): res[(row, c)] = int(colors)
                    elif colors is not None:
                        flat = list(colors) if hasattr(colors, "__iter__") else [colors]
                        for idx, c in enumerate(range(min_c, max_c+1)):
                            if idx < len(flat) and flat[idx] is not None:
                                try: res[(row, c)] = int(flat[idx])
                                except: pass
            except:
                for c in cols:
                    try:
                        color = ws.Cells(int(row)+1, int(c)+1).Interior.Color
                        if color is not None: res[(row, c)] = int(color)
                    except: pass
            return res

        for sheet_name, coords in by_sheet.items():
            ws = sheet_map.get(sheet_name) or sheet_map.get(str(sheet_name).strip())
            if not ws:
                for row, col in coords:
                    result.unknown.add((str(sheet_name), int(row), int(col)))
                result.errors.append(f"Лист не найден: {sheet_name}")
                continue
            
            by_row = defaultdict(list)
            for r, c in coords: by_row[r].append(c)
            
            for row, cols in by_row.items():
                interior_map = read_row(ws, row, cols)
                for col in cols:
                    try:
                        interior = interior_map.get((row, col))
                        if interior is None:
                            iv = ws.Cells(int(row)+1, int(col)+1).Interior.Color
                            interior = int(iv) if iv is not None else 16777215
                        if use_display:
                            try:
                                dv = ws.Cells(int(row)+1, int(col)+1).DisplayFormat.Interior.Color
                                display = int(dv) if dv is not None else interior
                            except Exception as exc:
                                raise RuntimeError(
                                    f"DisplayFormat недоступен: {exc}"
                                ) from exc
                        else:
                            display = interior

                        coord = (str(sheet_name), int(row), int(col))
                        decision = decide_excel_color(interior, display, use_display)
                        if decision.state == ColorState.UNKNOWN:
                            result.unknown.add(coord)
                            result.errors.append(
                                f"{sheet_name}!R{int(row) + 1}C{int(col) + 1}: "
                                f"{decision.error}"
                            )
                            continue
                        result.checked.add(coord)
                        if decision.state == ColorState.COLORED:
                            result.colored.add(coord)
                    except Exception as exc:
                        result.unknown.add((str(sheet_name), int(row), int(col)))
                        result.errors.append(
                            f"{sheet_name}!R{int(row) + 1}C{int(col) + 1}: {exc}"
                        )
    except Exception as e:
        import traceback
        result.errors.append(str(e))
        with open("excel_worker_error.log", "a", encoding="utf-8") as f:
            f.write(traceback.format_exc() + "\n")
    finally:
        if wb:
            try: wb.Close(False)
            except: pass
        try: excel.Quit()
        except: pass
        
    requested = {
        (str(sheet_name), int(row), int(col))
        for sheet_name, row, col in cells_list
    }
    missing = requested - result.checked - result.unknown
    if missing:
        result.unknown.update(missing)
        result.errors.append(f"Не проверено ячеек: {len(missing)}")
    print(json.dumps(result.to_payload()))

def main():
    import json
    import sys
    # sys.argv = ['exe', '--excel-worker', 'worker_script', 'fpath', 'json_file']
    fpath = sys.argv[3]
    with open(sys.argv[4], "r", encoding="utf-8") as f:
        data = json.load(f)
    check_cells_worker(fpath, data["cells"], data["use_display"])

if __name__ == "__main__":
    import json
    import sys
    # For direct execution testing
    fpath = sys.argv[1]
    with open(sys.argv[2], "r", encoding="utf-8") as f:
        data = json.load(f)
    check_cells_worker(fpath, data["cells"], data["use_display"])
