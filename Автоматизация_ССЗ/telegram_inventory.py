"""Безопасное подключение Telegram к очереди учета приборов."""

import html
import os

import requests


_CREDENTIAL_TARGET = "VAM/InventoryTelegramBot"
_API_BASE = "https://api.telegram.org"


class TelegramConnectionError(RuntimeError):
    pass


def _validate_token(token):
    token = str(token or "").strip()
    if ":" not in token or len(token) < 30:
        raise ValueError("Токен Telegram имеет неверный формат.")
    return token


def save_bot_token(token):
    """Сохранить токен в Windows Credential Manager, а не в config.json."""
    token = _validate_token(token)
    try:
        import win32cred
        win32cred.CredWrite({
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": _CREDENTIAL_TARGET,
            "UserName": "telegram_inventory_bot",
            "CredentialBlob": token,
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        }, 0)
    except Exception as exc:
        raise TelegramConnectionError(
            "Не удалось сохранить токен в диспетчере учетных данных Windows."
        ) from exc


def load_bot_token():
    env_token = os.environ.get("SSZ_TELEGRAM_BOT_TOKEN", "").strip()
    if env_token:
        return env_token
    try:
        import win32cred
        credential = win32cred.CredRead(
            _CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0
        )
        blob = credential.get("CredentialBlob", "")
        if isinstance(blob, bytes):
            blob = blob.decode("utf-16-le", errors="ignore").rstrip("\x00")
        return str(blob or "").strip()
    except Exception:
        return ""


def has_bot_token():
    return bool(load_bot_token())


def _request(token, method, payload=None, timeout=15):
    token = _validate_token(token)
    try:
        response = requests.post(
            f"{_API_BASE}/bot{token}/{method}",
            json=payload or {},
            timeout=timeout,
        )
        data = response.json()
    except Exception as exc:
        # Не включать URL/исключение: они могут содержать секретный токен.
        raise TelegramConnectionError("Не удалось связаться с Telegram.") from exc
    if not response.ok or not data.get("ok"):
        description = str(data.get("description") or "Telegram отклонил запрос")
        raise TelegramConnectionError(description)
    return data.get("result")


def test_connection(token, chat_id):
    bot = _request(token, "getMe")
    _request(token, "sendMessage", {
        "chat_id": str(chat_id).strip(),
        "text": "✅ Учет приборов подключен. Уведомления будут приходить сюда.",
    })
    return bot.get("username") or bot.get("first_name") or "Telegram-бот"


def send_attention_digest(chat_id, attention_items, limit=12):
    token = load_bot_token()
    if not token:
        raise TelegramConnectionError("Telegram-бот не настроен.")
    chat_id = str(chat_id or "").strip()
    if not chat_id:
        raise TelegramConnectionError("Не указан Telegram chat_id.")

    items = list(attention_items)
    critical = sum(item.get("priority") == "critical" for item in items)
    high = sum(item.get("priority") == "high" for item in items)
    medium = sum(item.get("priority") == "medium" for item in items)
    lines = [
        "<b>Что нужно проверить по приборам</b>",
        f"Всего задач: <b>{len(items)}</b>",
        f"Критичные: {critical} · Нужны данные: {high} · Предстоящие: {medium}",
        "",
    ]
    for index, item in enumerate(items[:limit], start=1):
        serial = item.get("serial_number") or "без номера"
        lines.extend([
            f"<b>{index}. {html.escape(str(item.get('issue') or 'Проверить прибор'))}</b>",
            f"{html.escape(str(item.get('device_name') or 'Прибор'))} · № {html.escape(str(serial))}",
            f"{html.escape(str(item.get('workshop_name') or ''))} · {html.escape(str(item.get('location_name') or ''))}",
            html.escape(str(item.get("request") or "")),
            "",
        ])
    if len(items) > limit:
        lines.append(f"Показаны первые {limit}. Остальные доступны в программе.")
    lines.append("Ответьте сообщением с заводским номером и найденными данными или приложите фото шильдика.")

    return _request(token, "sendMessage", {
        "chat_id": chat_id,
        "text": "\n".join(lines),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })
