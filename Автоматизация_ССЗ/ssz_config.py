import json
import os
from datetime import date

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

_DEFAULTS = {
    "duty_epoch": "2026-06-01",
    "kip_epoch": "2026-06-01",
    "min_ppr_per_day": 2,
    "max_ppr_per_day": 2,
    "redistribute_enabled": True,
    "max_bulk_days": 62,
    "cancel_watchdog_s": 15,
    "print_job_timeout_s": 30,
    "excel_force_kill_on_cancel": True,
    "progress_stale_s": 2.0,
    "prefer_xlsx": True,
    "warn_on_xls": True,
    "com_file_timeout_s": 90,
    "ppr_validation_max_age_s": 900,
    "bulk_extra_autosave_s": 20,
    "inventory_daily_plan_enabled": True,
    "inventory_daily_plan_size": 6,
    "inventory_daily_plan_cooldown_days": 14,
    "executor_1": "Наладчик КИПиА Таратов Д.В.",
    "executor_2": "Наладчик КИПиА Гаврилов М.Ю.",
    "overflow_executor": "Наладчик КИПиА Войтов А.М.",
    "session_user": "",
    "task_issuer": "Начальник лаборатории ТО КИПиА Богуславский Э.В.",
    "default_time": "08.00-20.00",
    "rules": "ИОТ 00-76-2024, \nПБ 01-2023",
    "task_1": "Выполнить два обхода и визуального осмотра оборудования КИП с отметкой на диаграммах. \nЗаменить заканчивающиеся складывающиеся, рулонные и дисковые диаграммы, проверить и наладить запись.",
    "place_1": "Цех № 47",
    "task_2": "Выполнить обход и визуальный осмотр оборудования КИП с отметкой на диаграммах. \nЗаменить заканчивающиеся складывающиеся, рулонные и дисковые диаграммы, проверить и наладить запись.",
    "place_2": "Цеха № 2, 6, 66-2, 34/66-2, ИСМ",
    "kip_dmm_place": "Цех № 47",
    "schedules_dir": "Графики",
    "history_file": "Учет_выполненных_ППР.txt",
    "ai_api_key": "",
    "ai_base_url": "https://openrouter.ai/api/v1/chat/completions",
    "ai_model": "openrouter/free",
    "telegram_chat_id": "410689929",
}


def _parse_date(value):
    y, m, d = value.split("-")
    return date(int(y), int(m), int(d))


def load_config():
    cfg = dict(_DEFAULTS)
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for key in _DEFAULTS:
                if key in raw:
                    cfg[key] = raw[key]
            # Special case for executor_overrides to keep user additions even if not in defaults
            if "executor_overrides" in raw:
                cfg["executor_overrides"] = raw["executor_overrides"]
        except Exception as exc:
            raise RuntimeError(
                f"Не удалось прочитать конфигурацию «{_CONFIG_PATH}»: {exc}"
            ) from exc
    # Secrets are supplied by the environment, so a shared config file does
    # not expose an API key in the project folder or backups.
    env_api_key = os.environ.get("SSZ_AI_API_KEY", "").strip()
    if env_api_key:
        cfg["ai_api_key"] = env_api_key
    cfg["duty_epoch"] = _parse_date(cfg["duty_epoch"])
    cfg["kip_epoch"] = _parse_date(cfg["kip_epoch"])
    cfg["cancel_watchdog_s"] = int(cfg.get("cancel_watchdog_s", 15))
    cfg["print_job_timeout_s"] = float(cfg.get("print_job_timeout_s", 30))
    cfg["excel_force_kill_on_cancel"] = bool(cfg.get("excel_force_kill_on_cancel", True))
    cfg["progress_stale_s"] = float(cfg.get("progress_stale_s", 2.0))
    cfg["prefer_xlsx"] = bool(cfg.get("prefer_xlsx", True))
    cfg["warn_on_xls"] = bool(cfg.get("warn_on_xls", True))
    cfg["ppr_validation_max_age_s"] = float(
        cfg.get("ppr_validation_max_age_s", 900)
    )
    cfg["com_file_timeout_s"] = int(cfg.get("com_file_timeout_s", 90))
    cfg["bulk_extra_autosave_s"] = int(cfg.get("bulk_extra_autosave_s", 20))
    
    # Ensure string defaults are strings
    for k in ["executor_1", "executor_2", "overflow_executor", "session_user", "task_issuer", "default_time", "rules", "task_1", "place_1", "task_2", "place_2", "kip_dmm_place", "schedules_dir", "history_file", "ai_api_key", "ai_base_url", "ai_model", "telegram_chat_id"]:
        cfg[k] = str(cfg.get(k, _DEFAULTS[k]))

    if "executor_overrides" not in cfg:
        cfg["executor_overrides"] = []
    return cfg


def save_config(cfg_dict):
    out = dict(cfg_dict)
    # Do not write credentials back to config.json, including when CONFIG was
    # populated from SSZ_AI_API_KEY.
    out["ai_api_key"] = ""
    if isinstance(out.get("duty_epoch"), date):
        out["duty_epoch"] = out["duty_epoch"].isoformat()
    if isinstance(out.get("kip_epoch"), date):
        out["kip_epoch"] = out["kip_epoch"].isoformat()
    temp_path = _CONFIG_PATH + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, _CONFIG_PATH)
    except Exception as exc:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        raise RuntimeError(f"Не удалось сохранить конфигурацию: {exc}") from exc


CONFIG = load_config()


def validate_config(cfg=None):
    """Проверка настроек без изменения рабочего состояния."""
    cfg = cfg or CONFIG
    errors = []
    warnings = []
    for key, label in (
        ("executor_1", "Сменный 1"),
        ("executor_2", "Сменный 2"),
        ("task_issuer", "Выдающий задание"),
        ("task_1", "Задание обхода 1"),
        ("task_2", "Задание обхода 2"),
    ):
        if not str(cfg.get(key) or "").strip():
            errors.append(f"Не заполнено поле «{label}»")
    if str(cfg.get("executor_1", "")).strip() == str(cfg.get("executor_2", "")).strip():
        errors.append("Сменный 1 и Сменный 2 не могут быть одним сотрудником")
    try:
        max_ppr = int(cfg.get("max_ppr_per_day", 2))
        if not 1 <= max_ppr <= 10:
            errors.append("Лимит ППР должен быть от 1 до 10")
    except (TypeError, ValueError):
        errors.append("Лимит ППР должен быть целым числом")
    try:
        age = float(cfg.get("ppr_validation_max_age_s", 900))
        if not 60 <= age <= 86400:
            errors.append("Срок актуальности анализа должен быть от 1 минуты до 24 часов")
    except (TypeError, ValueError):
        errors.append("Некорректный срок актуальности анализа")
    try:
        plan_size = int(cfg.get("inventory_daily_plan_size", 6))
        if not 1 <= plan_size <= 20:
            errors.append("Размер ежедневного плана базы должен быть от 1 до 20")
    except (TypeError, ValueError):
        errors.append("Некорректный размер ежедневного плана базы")
    for key, label in (("duty_epoch", "эпоха смен"), ("kip_epoch", "эпоха КИП")):
        if not isinstance(cfg.get(key), date):
            errors.append(f"Некорректная дата: {label}")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    schedules_dir = str(cfg.get("schedules_dir") or "Графики")
    if not os.path.isabs(schedules_dir):
        schedules_dir = os.path.join(base_dir, schedules_dir)
    if not os.path.isdir(schedules_dir):
        errors.append(f"Папка графиков не найдена: {schedules_dir}")
    elif not any(name.lower().endswith((".xls", ".xlsx")) for name in os.listdir(schedules_dir)):
        warnings.append("В папке графиков нет файлов Excel")
    if not os.path.isfile(os.path.join(base_dir, "Шаблон_ССЗ.xlsx")):
        errors.append("Не найден шаблон ССЗ")
    return {"errors": errors, "warnings": warnings}


def run_system_diagnostics(cfg=None, horizon_days=62):
    """Проверяет настройки, базы и кадровый календарь как единый контур."""
    from datetime import timedelta
    import sqlite3

    cfg = cfg or CONFIG
    result = validate_config(cfg)
    ok = []
    if not result["errors"]:
        ok.append("Основные настройки заполнены корректно")
    try:
        import win32com.client  # noqa: F401
        ok.append("Компоненты Microsoft Office доступны")
    except Exception as exc:
        result["errors"].append(f"Недоступна автоматизация Microsoft Office: {exc}")

    for label, path in (
        ("Основная база", os.path.join(os.path.dirname(__file__), "data", "app_data.db")),
        ("База приборов", os.path.join(os.path.dirname(__file__), "data", "inventory.db")),
    ):
        try:
            conn = sqlite3.connect(path)
            check = conn.execute("PRAGMA quick_check").fetchone()[0]
            conn.close()
            if check != "ok":
                raise RuntimeError(check)
            ok.append(f"{label}: целостность подтверждена")
        except Exception as exc:
            result["errors"].append(f"{label}: ошибка целостности — {exc}")

    try:
        from ssz_utils import get_executor
        today = date.today()
        for offset in range(int(horizon_days)):
            get_executor(today + timedelta(days=offset))
        ok.append(f"Табель сменных проверен на {horizon_days} дней вперёд")
    except Exception as exc:
        result["errors"].append(f"Табель персонала: {exc}")
    result["ok"] = ok
    return result
