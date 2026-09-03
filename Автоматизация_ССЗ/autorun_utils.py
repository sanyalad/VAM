import os
import sys

def setup_autorun():
    """Создает ярлык для запуска приложения (через Запуск_ССЗ.vbs) в папке Автозагрузки Windows."""
    try:
        import win32com.client
        startup_dir = os.path.join(os.getenv('APPDATA'), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
        if not os.path.exists(startup_dir):
            return False
            
        shortcut_path = os.path.join(startup_dir, "ВАМ_ССЗ_Автозапуск.lnk")
        if os.path.exists(shortcut_path):
            return True # Уже создан
            
        base_dir = os.path.dirname(os.path.abspath(__file__))
        target_path = os.path.join(base_dir, "Запуск_ССЗ.vbs")
        
        if not os.path.exists(target_path):
            target_path = os.path.join(base_dir, "main.py")
            
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = target_path
        shortcut.WorkingDirectory = base_dir
        shortcut.WindowStyle = 1 # Normal window
        if target_path.endswith(".vbs"):
            # VBS не может иметь иконку напрямую, используем python.exe
            shortcut.IconLocation = sys.executable
        shortcut.save()
        return True
    except Exception as e:
        print(f"Ошибка при настройке автозапуска: {e}")
        return False
