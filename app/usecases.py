from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from . import models
from . import rbac
from . import services


class DomainError(Exception):
    code: str = "error"

    def __init__(self, message: str = ""):
        super().__init__(message or self.__class__.__name__)


class PermissionDeniedError(DomainError):
    code = "forbidden"


class StatusChangeForbiddenError(PermissionDeniedError):
    code = "forbidden_status_change"


class RequestNotFoundError(DomainError):
    code = "request_not_found"


class HelpRequestNotFoundError(DomainError):
    code = "help_not_found"


class HelpRequestAlreadyOpenError(DomainError):
    code = "help_exists"


class BusinessRuleViolationError(DomainError):
    code = "db_error"


@dataclass(frozen=True)
class RequestInput:
    id: Optional[int]
    start_date: date
    equipment_type_id: int
    equipment_model_name: str
    issue_type_id: Optional[int]
    problem_description: str
    status_id: Optional[int]
    completion_date: Optional[date]
    due_date: Optional[date]
    repair_parts: Optional[str]
    master_id: Optional[int]
    client_id: Optional[int]


@dataclass(frozen=True)
class HelpRequestCreateInput:
    request_id: int
    message: str
    proposed_due_date: Optional[date]


@dataclass(frozen=True)
class HelpRequestCloseInput:
    help_id: int
    resolution_note: str
    assigned_master_id: Optional[int]
    new_due_date: Optional[date]


def _resolve_equipment_and_issue(
    db: Session,
    data: RequestInput,
) -> tuple[models.EquipmentModel, models.IssueType]:
    equipment_model = services.get_or_create_equipment_model(
        db=db,
        equipment_type_id=data.equipment_type_id,
        model_name=data.equipment_model_name,
    )

    if data.issue_type_id:
        issue_type_obj = db.get(models.IssueType, data.issue_type_id)
        if not issue_type_obj:
            issue_type_obj = services.get_or_create_issue_type(
                db=db,
                problem_description=data.problem_description,
            )
    else:
        issue_type_obj = services.get_or_create_issue_type(
            db=db,
            problem_description=data.problem_description,
        )

    return equipment_model, issue_type_obj


def _resolve_new_status_for_create(
    db: Session,
    user: models.User,
    data: RequestInput,
) -> models.RequestStatus:
    role = rbac.role_name(user)

    if role == services.ROLE_CLIENT:
        return services.get_new_request_status(db=db)

    if data.status_id is None:
        raise BusinessRuleViolationError(
            "Для сотрудника сервиса необходимо явно указать статус заявки.",
        )

    status_obj = db.get(models.RequestStatus, data.status_id)
    if not status_obj:
        raise BusinessRuleViolationError("Указан несуществующий статус заявки.")

    return status_obj


def _resolve_new_status_for_update(
    db: Session,
    user: models.User,
    req: models.RepairRequest,
    data: RequestInput,
) -> models.RequestStatus:
    role = rbac.role_name(user)
    old_status = req.status

    if role == services.ROLE_CLIENT:
        return old_status

    if data.status_id is None or data.status_id == old_status.id:
        return old_status

    new_status = db.get(models.RequestStatus, data.status_id)
    if not new_status:
        raise BusinessRuleViolationError("Указан несуществующий статус заявки.")

    if not rbac.user_can_change_status(
        user=user,
        old_status=old_status,
        new_status=new_status,
    ):
        raise StatusChangeForbiddenError(
            "Пользователь не имеет права выполнять такой переход статуса.",
        )

    return new_status


def _apply_completion_date(
    req: models.RepairRequest,
    new_status: models.RequestStatus,
    data: RequestInput,
) -> None:
    if new_status.is_final:
        req.completion_date = data.completion_date or date.today()
        return

    req.completion_date = data.completion_date


def _apply_due_date(
    user: models.User,
    req: models.RepairRequest,
    data: RequestInput,
) -> None:
    role = rbac.role_name(user)

    if role in (
        services.ROLE_MANAGER,
        services.ROLE_OPERATOR,
        services.ROLE_QUALITY_MANAGER,
    ):
        req.due_date = data.due_date
        return

    if req.id is None:
        req.due_date = None


def _apply_repair_parts(
    user: models.User,
    req: models.RepairRequest,
    data: RequestInput,
) -> None:
    role = rbac.role_name(user)

    if role in (
        services.ROLE_MANAGER,
        services.ROLE_OPERATOR,
        services.ROLE_MASTER,
        services.ROLE_SPECIALIST,
    ):
        text = (data.repair_parts or "").strip()
        req.repair_parts = text or None
        return

    if req.id is None:
        req.repair_parts = None


def _apply_master(
    user: models.User,
    req: models.RepairRequest,
    data: RequestInput,
) -> None:
    if rbac.user_can_assign_master(user):
        req.master_id = data.master_id if data.master_id else None
        return

    if req.id is None:
        req.master_id = None


def _apply_client(
    user: models.User,
    req: models.RepairRequest,
    data: RequestInput,
) -> None:
    role = rbac.role_name(user)

    if role == services.ROLE_CLIENT:
        req.client_id = user.id
        return

    if role in (services.ROLE_MANAGER, services.ROLE_OPERATOR):
        if not data.client_id:
            raise BusinessRuleViolationError("Не указан заказчик заявки.")
        req.client_id = int(data.client_id)
        return

    if req.id is None:
        raise BusinessRuleViolationError(
            "Роль не может создавать заявку от имени заказчика.",
        )


def save_request(
    db: Session,
    user: models.User,
    data: RequestInput,
) -> models.RepairRequest:
    is_edit = data.id is not None

    equipment_model, issue_type_obj = _resolve_equipment_and_issue(
        db=db,
        data=data,
    )

    if is_edit:
        req = db.get(models.RepairRequest, data.id)
        if not req:
            raise RequestNotFoundError("Заявка не найдена.")

        if not rbac.user_can_edit_request(user=user, req=req):
            raise PermissionDeniedError(
                "Нет прав на редактирование этой заявки.",
            )

        new_status = _resolve_new_status_for_update(
            db=db,
            user=user,
            req=req,
            data=data,
        )

    else:
        if not rbac.user_can_create_request(user):
            raise PermissionDeniedError(
                "Нет прав на создание новой заявки.",
            )

        req = models.RepairRequest()
        new_status = _resolve_new_status_for_create(
            db=db,
            user=user,
            data=data,
        )

    req.start_date = data.start_date
    req.equipment_model_id = equipment_model.id
    req.issue_type_id = issue_type_obj.id
    req.problem_description = data.problem_description
    req.status_id = new_status.id

    _apply_completion_date(req=req, new_status=new_status, data=data)
    _apply_due_date(user=user, req=req, data=data)
    _apply_repair_parts(user=user, req=req, data=data)
    _apply_master(user=user, req=req, data=data)
    _apply_client(user=user, req=req, data=data)

    db.add(req)

    return req


def delete_request(
    db: Session,
    user: models.User,
    request_id: int,
) -> None:
    req = db.get(models.RepairRequest, request_id)
    if not req:
        raise RequestNotFoundError("Заявка не найдена.")

    if not rbac.user_can_delete_request(user=user):
        raise PermissionDeniedError("Удалять заявки могут только Менеджер и Оператор.")

    db.delete(req)


def add_comment(
    db: Session,
    user: models.User,
    request_id: int,
    message: str,
) -> models.RequestComment:
    req = db.get(models.RepairRequest, request_id)
    if not req:
        raise RequestNotFoundError("Заявка не найдена.")

    if not rbac.user_can_add_comment(user=user, req=req):
        raise PermissionDeniedError(
            "Комментарий может добавлять только мастер по своей заявке.",
        )

    msg_clean = (message or "").strip()
    if not msg_clean:
        raise BusinessRuleViolationError("Текст комментария не может быть пустым.")

    comment = models.RequestComment(
        request_id=request_id,
        master_id=user.id,
        message=msg_clean,
    )
    db.add(comment)

    return comment


def create_help_request(
    db: Session,
    user: models.User,
    data: HelpRequestCreateInput,
) -> models.HelpRequest:
    if not rbac.user_can_create_help_request(user):
        raise PermissionDeniedError("Запрос помощи может создавать только мастер.")

    req = db.get(models.RepairRequest, data.request_id)
    if not req:
        raise RequestNotFoundError("Заявка не найдена.")

    if req.master_id != user.id:
        raise PermissionDeniedError("Запрос помощи доступен только для своей заявки.")

    open_exists = (
        db.query(models.HelpRequest)
        .filter(models.HelpRequest.request_id == data.request_id)
        .filter(models.HelpRequest.status == "open")
        .first()
    )
    if open_exists:
        raise HelpRequestAlreadyOpenError("По этой заявке уже есть открытый запрос помощи.")

    msg_clean = (data.message or "").strip()
    if not msg_clean:
        raise BusinessRuleViolationError("Текст запроса помощи не может быть пустым.")

    help_req = models.HelpRequest(
        request_id=data.request_id,
        created_by_master_id=user.id,
        status="open",
        message=msg_clean,
        proposed_due_date=data.proposed_due_date,
    )
    db.add(help_req)

    return help_req


def close_help_request(
    db: Session,
    user: models.User,
    data: HelpRequestCloseInput,
) -> models.HelpRequest:
    if not rbac.user_can_handle_help_request(user):
        raise PermissionDeniedError("Обрабатывать запросы помощи может только менеджер по качеству.")

    help_req = db.get(models.HelpRequest, data.help_id)
    if not help_req:
        raise HelpRequestNotFoundError("Запрос помощи не найден.")

    if help_req.status != "open":
        raise BusinessRuleViolationError("Запрос помощи уже закрыт.")

    req = db.get(models.RepairRequest, help_req.request_id)
    if not req:
        raise RequestNotFoundError("Заявка не найдена.")

    if data.new_due_date is not None and data.new_due_date < req.start_date:
        raise BusinessRuleViolationError("Новый срок выполнения не может быть раньше даты создания заявки.")

    if data.assigned_master_id is not None:
        master_user = db.get(models.User, data.assigned_master_id)
        if not master_user or not services.is_master_role(master_user.role.name):
            raise BusinessRuleViolationError("Назначенный исполнитель должен быть пользователем с ролью «Мастер».")

        req.master_id = master_user.id
        help_req.assigned_master_id = master_user.id

    if data.new_due_date is not None:
        req.due_date = data.new_due_date

    note_clean = (data.resolution_note or "").strip()
    help_req.resolution_note = note_clean or None

    help_req.quality_manager_id = user.id
    help_req.status = "closed"
    help_req.closed_at = datetime.now(tz=timezone.utc)

    db.add(req)
    db.add(help_req)

    return help_req