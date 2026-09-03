import os

def fix_file(fname):
    if not os.path.exists(fname): return
    with open(fname, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    out = []
    for line in lines:
        if line.strip() == "pass" and out and out[-1].strip() == "# pythoncom.CoUninitialize()":
            indent = out[-1][:len(out[-1]) - len(out[-1].lstrip())]
            out.append(indent + "pass\n")
        else:
            out.append(line)
            
    with open(fname, 'w', encoding='utf-8') as f:
        f.writelines(out)

fix_file('ppr_printer.py')
fix_file('printer_utils.py')
fix_file('exam_parser.py')
fix_file('xls_color_cache.py')
