"""Append-only log of long-running operations for debugging, powered by SQLite."""

from data_manager import (
    db_log_operation,
    db_log_audit,
    db_read_log_tail,
)


def log_operation(event, detail=""):
    db_log_operation(event, detail)


def log_business_event(event, detail=""):
    db_log_operation(f"BUSINESS_{event}", detail)


def log_audit(lines):
    message = "\n".join(lines) if isinstance(lines, list) else str(lines)
    db_log_audit(message)


def read_log_tail(max_lines=100):
    return db_read_log_tail(max_lines)
