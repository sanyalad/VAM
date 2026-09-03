import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
import csv
import os
from datetime import datetime

DB_FILE = 'kipia_data.db'

def add_months(sourcedate, months):
    """Добавляет месяцы к дате (встроенная альтернатива dateutil.relativedelta)"""
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, [31,
        29 if year%4==0 and (not year%100==0 or year%400==0) else 28,
        31,30,31,30,31,31,30,31,30,31][month-1])
    return datetime(year, month, day)

class KipiaApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Учет КИПиА")
        self.root.geometry("1250x700")
        
        # Настройка стилей
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Treeview.Heading", font=('Arial', 10, 'bold'))
        style.configure("Treeview", font=('Arial', 10), rowheight=25)
        
        self.checked_ids = set()
        self.init_db()
        self.create_gui()
        self.load_data()

    def init_db(self):
        self.conn = sqlite3.connect(DB_FILE)
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop TEXT,
                name TEXT,
                model TEXT,
                scale TEXT,
                last_date TEXT,
                interval_mo INTEGER,
                next_date TEXT,
                notes TEXT
            )
        ''')
        self.conn.commit()

    def create_gui(self):
        # --- Левая панель (Форма и кнопки) ---
        left_frame = ttk.Frame(self.root, padding=10, width=300)
        left_frame.pack(side=tk.LEFT, fill=tk.Y)
        left_frame.pack_propagate(False)

        ttk.Label(left_frame, text="Цех (например, Ц47):").pack(anchor=tk.W)
        self.shop_var = tk.StringVar()
        ttk.Entry(left_frame, textvariable=self.shop_var).pack(fill=tk.X, pady=(0, 10))

        ttk.Label(left_frame, text="Название прибора:").pack(anchor=tk.W)
        self.name_var = tk.StringVar()
        ttk.Entry(left_frame, textvariable=self.name_var).pack(fill=tk.X, pady=(0, 10))

        ttk.Label(left_frame, text="Модель/Зав.№:").pack(anchor=tk.W)
        self.model_var = tk.StringVar()
        ttk.Entry(left_frame, textvariable=self.model_var).pack(fill=tk.X, pady=(0, 10))

        ttk.Label(left_frame, text="Шкала:").pack(anchor=tk.W)
        self.scale_var = tk.StringVar()
        ttk.Entry(left_frame, textvariable=self.scale_var).pack(fill=tk.X, pady=(0, 10))

        ttk.Label(left_frame, text="Дата поверки (ДД.ММ.ГГГГ):").pack(anchor=tk.W)
        self.last_date_var = tk.StringVar()
        ttk.Entry(left_frame, textvariable=self.last_date_var).pack(fill=tk.X, pady=(0, 10))

        ttk.Label(left_frame, text="Интервал (мес):").pack(anchor=tk.W)
        self.interval_var = tk.StringVar()
        ttk.Entry(left_frame, textvariable=self.interval_var).pack(fill=tk.X, pady=(0, 10))

        ttk.Label(left_frame, text="Пометки:").pack(anchor=tk.W)
        self.notes_var = tk.StringVar()
        ttk.Entry(left_frame, textvariable=self.notes_var).pack(fill=tk.X, pady=(0, 10))

        self.id_var = tk.StringVar() # Скрытый ID для редактирования

        # Кнопки CRUD
        ttk.Button(left_frame, text="Сохранить / Добавить", command=self.save_device).pack(fill=tk.X, pady=2)
        ttk.Button(left_frame, text="Очистить форму", command=self.clear_form).pack(fill=tk.X, pady=2)
        ttk.Button(left_frame, text="Удалить выбранный", command=self.delete_device).pack(fill=tk.X, pady=2)

        ttk.Separator(left_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)

        # Кнопки Импорт/Экспорт
        ttk.Button(left_frame, text="Импорт из CSV", command=self.import_csv).pack(fill=tk.X, pady=2)
        
        export_frame = ttk.LabelFrame(left_frame, text="Экспорт в CSV", padding=5)
        export_frame.pack(fill=tk.X, pady=5)
        
        self.export_scale_var = tk.BooleanVar(value=True)
        self.export_notes_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(export_frame, text="Вкл. столбец 'Шкала'", variable=self.export_scale_var).pack(anchor=tk.W)
        ttk.Checkbutton(export_frame, text="Вкл. столбец 'Пометки'", variable=self.export_notes_var).pack(anchor=tk.W)
        
        ttk.Button(export_frame, text="Выгрузить всё", command=lambda: self.export_csv('all')).pack(fill=tk.X, pady=2)
        ttk.Button(export_frame, text="Выгрузить отмеченные (☑)", command=lambda: self.export_csv('checked')).pack(fill=tk.X, pady=2)
        ttk.Button(export_frame, text="Выгрузить требующие поверки", command=lambda: self.export_csv('critical')).pack(fill=tk.X, pady=2)

        ttk.Separator(left_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)
        ttk.Button(left_frame, text="📂 Открыть схемы цехов", command=self.open_schemas).pack(fill=tk.X, pady=2)

        # --- Правая панель (Таблица) ---
        right_frame = ttk.Frame(self.root, padding=10)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        columns = ("check", "id", "shop", "name", "model", "scale", "last_date", "interval", "next_date", "notes")
        self.tree = ttk.Treeview(right_frame, columns=columns, show="headings")

        self.tree.heading("check", text="☑/☐")
        self.tree.column("check", width=40, anchor=tk.CENTER, stretch=tk.NO)
        
        self.tree.heading("id", text="ID")
        self.tree.column("id", width=40, anchor=tk.CENTER, stretch=tk.NO)
        
        self.tree.heading("shop", text="Цех")
        self.tree.column("shop", width=100)
        
        self.tree.heading("name", text="Название")
        self.tree.column("name", width=120)
        
        self.tree.heading("model", text="Модель/Зав.№")
        self.tree.column("model", width=120)
        
        self.tree.heading("scale", text="Шкала")
        self.tree.column("scale", width=80)
        
        self.tree.heading("last_date", text="Дата пов.")
        self.tree.column("last_date", width=90, anchor=tk.CENTER)
        
        self.tree.heading("interval", text="Инт.(мес)")
        self.tree.column("interval", width=70, anchor=tk.CENTER)
        
        self.tree.heading("next_date", text="След. пов.")
        self.tree.column("next_date", width=90, anchor=tk.CENTER)
        
        self.tree.heading("notes", text="Пометки")
        self.tree.column("notes", width=150)

        # Скроллбар
        scrollbar = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True)

        # Биндинги
        self.tree.bind("<ButtonRelease-1>", self.on_tree_click)

        # Теги для цветов
        self.tree.tag_configure('danger', background='#ffcccc') # Красный - просрочено
        self.tree.tag_configure('warning', background='#ffffcc') # Желтый - <= 30 дней
        self.tree.tag_configure('info', background='#cce5ff') # Синий - Спецсталь <= 90 дней

    def calculate_next_date(self, last_date_str, interval):
        try:
            d = datetime.strptime(last_date_str, "%d.%m.%Y")
            next_d = add_months(d, int(interval))
            return next_d.strftime("%d.%m.%Y")
        except Exception:
            return ""

    def save_device(self):
        shop = self.shop_var.get().strip()
        name = self.name_var.get().strip()
        model = self.model_var.get().strip()
        scale = self.scale_var.get().strip()
        last_date = self.last_date_var.get().strip()
        interval = self.interval_var.get().strip()
        notes = self.notes_var.get().strip()
        dev_id = self.id_var.get()

        if not all([shop, name, last_date, interval]):
            messagebox.showerror("Ошибка", "Заполните обязательные поля (Цех, Название, Дата, Интервал)")
            return

        next_date = self.calculate_next_date(last_date, interval)
        if not next_date:
            messagebox.showerror("Ошибка", "Неверный формат даты (нужно ДД.ММ.ГГГГ) или интервала")
            return

        if dev_id:
            self.cursor.execute('''
                UPDATE devices SET shop=?, name=?, model=?, scale=?, last_date=?, interval_mo=?, next_date=?, notes=?
                WHERE id=?
            ''', (shop, name, model, scale, last_date, int(interval), next_date, notes, dev_id))
        else:
            self.cursor.execute('''
                INSERT INTO devices (shop, name, model, scale, last_date, interval_mo, next_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (shop, name, model, scale, last_date, int(interval), next_date, notes))

        self.conn.commit()
        self.clear_form()
        self.load_data()

    def delete_device(self):
        dev_id = self.id_var.get()
        if dev_id:
            if messagebox.askyesno("Подтверждение", "Удалить выбранный прибор?"):
                self.cursor.execute('DELETE FROM devices WHERE id=?', (dev_id,))
                self.conn.commit()
                self.clear_form()
                self.load_data()

    def clear_form(self):
        self.id_var.set("")
        self.shop_var.set("")
        self.name_var.set("")
        self.model_var.set("")
        self.scale_var.set("")
        self.last_date_var.set("")
        self.interval_var.set("")
        self.notes_var.set("")

    def load_data(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        self.cursor.execute('SELECT * FROM devices')
        rows = self.cursor.fetchall()

        today = datetime.now()

        for row in rows:
            dev_id = row[0]
            shop = row[1]
            next_date_str = row[7]

            check_symbol = "☑" if dev_id in self.checked_ids else "☐"
            display_values = (check_symbol,) + row

            tag = ''
            try:
                next_d = datetime.strptime(next_date_str, "%d.%m.%Y")
                days_left = (next_d - today).days

                if days_left < 0:
                    tag = 'danger'
                elif days_left <= 30:
                    tag = 'warning'
                elif ('Ц47' in shop or 'Ц66' in shop) and days_left <= 90:
                    tag = 'info'
            except:
                pass

            self.tree.insert("", tk.END, values=display_values, tags=(tag,))

    def on_tree_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region == "cell":
            column = self.tree.identify_column(event.x)
            item = self.tree.identify_row(event.y)
            values = self.tree.item(item, "values")
            if not values: return

            dev_id = int(values[1])

            if column == "#1": # Клик по галочке
                if dev_id in self.checked_ids:
                    self.checked_ids.remove(dev_id)
                else:
                    self.checked_ids.add(dev_id)
                self.load_data()
            else:
                # Перенос данных в форму
                self.id_var.set(values[1])
                self.shop_var.set(values[2])
                self.name_var.set(values[3])
                self.model_var.set(values[4])
                self.scale_var.set(values[5])
                self.last_date_var.set(values[6])
                self.interval_var.set(values[7])
                self.notes_var.set(values[9])

    def import_csv(self):
        filepath = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if not filepath: return

        try:
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f, delimiter=';')
                header = next(reader, None) # Пропуск заголовка
                for row in reader:
                    if len(row) >= 5:
                        shop = row[0]
                        name = row[1]
                        model = row[2]
                        last_date = row[3]
                        try:
                            interval = int(row[4])
                        except:
                            continue

                        scale = row[5] if len(row) > 5 else ""
                        notes = row[6] if len(row) > 6 else ""

                        next_date = self.calculate_next_date(last_date, interval)

                        self.cursor.execute('''
                            INSERT INTO devices (shop, name, model, scale, last_date, interval_mo, next_date, notes)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (shop, name, model, scale, last_date, interval, next_date, notes))
            self.conn.commit()
            self.load_data()
            messagebox.showinfo("Успех", "Данные успешно импортированы")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка импорта: {e}")

    def export_csv(self, mode):
        filepath = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV Files", "*.csv")])
        if not filepath: return

        include_scale = self.export_scale_var.get()
        include_notes = self.export_notes_var.get()

        try:
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';')
                
                # Формируем заголовок
                header = ["Цех", "Название", "Модель"]
                if include_scale: header.append("Шкала")
                header.extend(["Дата поверки", "Интервал", "След. поверка"])
                if include_notes: header.append("Пометки")
                writer.writerow(header)

                for item in self.tree.get_children():
                    values = self.tree.item(item, "values")
                    tags = self.tree.item(item, "tags")
                    dev_id = int(values[1])

                    if mode == 'checked' and dev_id not in self.checked_ids:
                        continue
                    if mode == 'critical' and not tags: # Если нет тегов (цветов), пропускаем
                        continue

                    # Формируем строку
                    row = [values[2], values[3], values[4]] # shop, name, model
                    if include_scale: row.append(values[5])
                    row.extend([values[6], values[7], values[8]]) # last_date, interval, next_date
                    if include_notes: row.append(values[9])
                    
                    writer.writerow(row)
                    
            messagebox.showinfo("Успех", "Данные успешно экспортированы")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка экспорта: {e}")

    def open_schemas(self):
        schema_path = "schemas"
        if not os.path.exists(schema_path):
            try:
                os.makedirs(schema_path)
                messagebox.showinfo("Информация", f"Создана папка '{schema_path}' рядом с программой.\nПоместите туда схемы цехов (PDF, картинки).")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось создать папку: {e}")
                return
        try:
            os.startfile(schema_path)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть папку: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = KipiaApp(root)
    root.mainloop()
