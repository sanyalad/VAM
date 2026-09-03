"""Черновик доп. заданий для массовой генерации (не теряется при отмене/COM)."""

from datetime import date, datetime

def save_bulk_extra_draft(start_date, end_date, extra_by_date):
    """extra_by_date: {'yyyy-mm-dd': [{'work','place'}, ...]}"""
    from data_manager import db_save_bulk_extra
    
    success = True
    if extra_by_date:
        for k, v in extra_by_date.items():
            if not db_save_bulk_extra(k, v):
                success = False
    return success


def load_bulk_extra_draft(start_date, end_date):
    from data_manager import db_load_bulk_extra
    existing = db_load_bulk_extra()
    res = {}
    
    if isinstance(start_date, datetime):
        start_date = start_date.date()
    if isinstance(end_date, datetime):
        end_date = end_date.date()
        
    for k, tasks in existing.items():
        try:
            # Try to parse %d.%m.%Y first, then fallback to %Y-%m-%d for backwards compatibility
            try:
                d = datetime.strptime(k, "%d.%m.%Y").date()
            except ValueError:
                d = datetime.strptime(k, "%Y-%m-%d").date()
            if start_date <= d <= end_date:
                # Always use %d.%m.%Y in the returned dict, as that's what ssz_window expects
                res[d.strftime("%d.%m.%Y")] = tasks
        except Exception:
            pass
    return res


def draft_info():
    from data_manager import db_load_bulk_extra
    try:
        by_date = db_load_bulk_extra()
        n_days = len(by_date)
        n_tasks = sum(len(v) for v in by_date.values())
        return {
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "days": n_days,
            "tasks": n_tasks,
        }
    except Exception:
        return None
