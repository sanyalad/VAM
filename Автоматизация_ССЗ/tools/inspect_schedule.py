import pandas as pd
import sys

def main():
    try:
        xls = pd.ExcelFile('График_д-мм_2026-06-01_2026-06-30.xlsx')
        sheet = xls.sheet_names[0]
        df = pd.read_excel(xls, sheet_name=sheet)
        print(f"Sheet: {sheet}")
        print("First 20 rows, 5 columns:")
        print(df.iloc[:20, :5].to_string())
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    # Fix console encoding issue for cyrillic
    sys.stdout.reconfigure(encoding='utf-8')
    main()
