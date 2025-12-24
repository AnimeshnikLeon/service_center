from datetime import date
from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from fastapi import Request


def parse_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None

    cleaned = str(value).strip()
    if not cleaned:
        return None

    try:
        return int(cleaned)
    except ValueError:
        return None


def parse_date(
    value: Optional[str],
    field_errors: Dict[str, str],
    field_key: str,
    field_title: str,
) -> Optional[date]:
    cleaned = (value or "").strip()
    if not cleaned:
        field_errors[field_key] = f"Укажите дату для поля «{field_title}»."
        return None

    try:
        parsed = datetime.strptime(cleaned, "%Y-%m-%d").date()
    except ValueError:
        field_errors[field_key] = (
            f"Неверный формат даты для поля «{field_title}». "
            f"Используйте формат ГГГГ-ММ-ДД."
        )
        return None

    return parsed


def build_status_messages(request: Request) -> List[Dict[str, Any]]:
    code = request.query_params.get("status")
    if not code:
        return []

    mapping = {
        "login_required": (
            "warning",
            "Требуется вход",
            "Для продолжения войдите в систему.",
        ),
        "login_failed": (
            "error",
            "Ошибка входа",
            "Неверный логин или пароль.",
        ),
        "logout_ok": (
            "info",
            "Выход выполнен",
            "Сеанс завершён.",
        ),
        "request_created": (
            "success",
            "Заявка создана",
            "Новая заявка успешно сохранена.",
        ),
        "request_updated": (
            "success",
            "Заявка обновлена",
            "Изменения успешно сохранены.",
        ),
        "request_deleted": (
            "info",
            "Заявка удалена",
            "Запись удалена без ошибок.",
        ),
        "request_not_found": (
            "error",
            "Заявка не найдена",
            "Запрошенная заявка не существует или уже удалена.",
        ),
        "forbidden": (
            "error",
            "Доступ запрещён",
            "У вас нет прав на выполнение этого действия.",
        ),
        "forbidden_status_change": (
            "error",
            "Недопустимое изменение статуса",
            "У вас нет прав изменять статус этой заявки.",
        ),
        "comment_added": (
            "success",
            "Комментарий добавлен",
            "Сообщение мастера сохранено.",
        ),
        "comment_empty": (
            "error",
            "Комментарий не сохранён",
            "Текст комментария не может быть пустым.",
        ),
        "db_error": (
            "error",
            "Ошибка сохранения",
            "Не удалось сохранить изменения. "
            "Повторите попытку позже или обратитесь к администратору.",
        ),
        "user_created": (
            "success",
            "Пользователь создан",
            "Новый пользователь успешно добавлен в систему.",
        ),
        "user_updated": (
            "success",
            "Пользователь обновлён",
            "Изменения данных пользователя сохранены.",
        ),
        "user_deleted": (
            "info",
            "Пользователь удалён",
            "Запись пользователя удалена.",
        ),
        "user_delete_failed": (
            "error",
            "Удаление невозможно",
            "Невозможно удалить пользователя, так как он связан с заявками или комментариями.",
        ),
        "user_not_found": (
            "error",
            "Пользователь не найден",
            "Запрошенный пользователь не существует или уже удалён.",
        ),
        "help_created": (
            "success",
            "Запрос помощи создан",
            "Запрос помощи отправлен менеджеру по качеству.",
        ),
        "help_closed": (
            "success",
            "Запрос помощи закрыт",
            "Запрос помощи обработан и закрыт.",
        ),
        "help_exists": (
            "warning",
            "Запрос уже существует",
            "По этой заявке уже есть открытый запрос помощи.",
        ),
        "help_not_found": (
            "error",
            "Запрос помощи не найден",
            "Запрошенная запись не существует или уже удалена.",
        ),
    }

    msg = mapping.get(code)
    if not msg:
        return []

    msg_type, title, text = msg
    return [{"type": msg_type, "title": title, "text": text}]