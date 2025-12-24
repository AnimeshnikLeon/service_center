from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Generator, Optional
import io

from fastapi import Depends
from fastapi import FastAPI
from fastapi import Form
from fastapi import Request
from fastapi import status
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
import qrcode

from . import models
from . import rbac
from . import services
from . import usecases
from .database import session_local
from .ui_utils import build_status_messages
from .ui_utils import parse_date
from .ui_utils import parse_int


app = FastAPI(title="Учет заявок на ремонт бытовой техники")

base_dir = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(base_dir / "templates"))
app.mount(
    "/static",
    StaticFiles(directory=str(base_dir / "static")),
    name="static",
)

templates.env.globals["can_edit_request"] = rbac.user_can_edit_request
templates.env.globals["can_delete_request"] = rbac.user_can_delete_request

app.add_middleware(
    SessionMiddleware,
    secret_key=services.ensure_default_secret_key(),
    max_age=60 * 60 * 8,
    same_site="lax",
)


def get_db() -> Generator[Session, None, None]:
    db = session_local()
    try:
        yield db
    finally:
        db.close()


def current_user_optional(
    request: Request,
    db: Session,
) -> Optional[models.User]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None

    user = db.get(models.User, int(user_id))
    return user


@app.get("/", response_class=HTMLResponse)
def root(
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            url="/ui/login?status=login_required",
            status_code=status.HTTP_302_FOUND,
        )

    return RedirectResponse(
        url="/ui/requests",
        status_code=status.HTTP_302_FOUND,
    )


# ===========================
# Auth
# ===========================


@app.get("/ui/login", response_class=HTMLResponse)
def ui_login(request: Request):
    context = {
        "request": request,
        "active_page": "login",
        "messages": build_status_messages(request),
        "form_data": {"login": ""},
        "field_errors": {},
        "user": None,
        "role": "",
    }
    return templates.TemplateResponse("login.html", context)


@app.post("/ui/login", response_class=HTMLResponse)
def ui_login_post(
    request: Request,
    login: str = Form(default=""),
    password: str = Form(default=""),
    db: Session = Depends(get_db),
):
    user = services.authenticate_user(db=db, login=login, password=password)
    if not user:
        return RedirectResponse(
            url="/ui/login?status=login_failed",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    request.session["user_id"] = user.id

    return RedirectResponse(
        url="/ui/requests",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/ui/logout")
def ui_logout(request: Request):
    request.session.clear()

    return RedirectResponse(
        url="/ui/login?status=logout_ok",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ===========================
# Requests (list/view/form)
# ===========================


@app.get("/ui/requests", response_class=HTMLResponse)
def ui_requests_list(
    request: Request,
    q: str = "",
    status_id: str = "",
    equipment_type_id: str = "",
    issue_type_id: str = "",
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            url="/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    role = rbac.role_name(user)

    query = (
        db.query(models.RepairRequest)
        .join(models.EquipmentModel)
        .join(models.EquipmentType)
        .join(models.IssueType)
        .join(models.RequestStatus)
        .join(
            models.User,
            models.RepairRequest.client_id == models.User.id,
        )
        .order_by(models.RepairRequest.id.desc())
    )

    if role == services.ROLE_CLIENT:
        query = query.filter(models.RepairRequest.client_id == user.id)

    if services.is_master_role(role):
        query = query.filter(models.RepairRequest.master_id == user.id)

    q_clean = (q or "").strip()
    if q_clean:
        if q_clean.isdigit():
            query = query.filter(models.RepairRequest.id == int(q_clean))
        else:
            query = query.filter(
                models.RepairRequest.problem_description.ilike(f"%{q_clean}%"),
            )

    s_id = parse_int(status_id)
    if s_id:
        query = query.filter(models.RepairRequest.status_id == s_id)

    e_id = parse_int(equipment_type_id)
    if e_id:
        query = query.filter(models.EquipmentModel.equipment_type_id == e_id)

    it_id = parse_int(issue_type_id)
    if it_id:
        query = query.filter(models.RepairRequest.issue_type_id == it_id)

    items = query.all()
    reference_lookups = services.load_reference_lookups(db=db)

    messages = build_status_messages(request)
    if not items and (q_clean or s_id or e_id or it_id):
        messages = messages + [
            {
                "type": "info",
                "title": "Нет результатов",
                "text": "По фильтрам заявки не найдены.",
            }
        ]

    context = {
        "request": request,
        "active_page": "requests",
        "messages": messages,
        "user": user,
        "role": role,
        "requests": items,
        "statuses": reference_lookups.statuses,
        "equipment_types": reference_lookups.equipment_types,
        "issue_types": reference_lookups.issue_types,
        "filters": {
            "q": q_clean,
            "status_id": s_id,
            "equipment_type_id": e_id,
            "issue_type_id": it_id,
        },
    }
    return templates.TemplateResponse("requests.html", context)


@app.get("/ui/requests/new", response_class=HTMLResponse)
def ui_request_new(
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            url="/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not rbac.user_can_create_request(user):
        return RedirectResponse(
            url="/ui/requests?status=forbidden",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    role = rbac.role_name(user)
    lookups = services.load_request_form_lookups(db=db)

    form_data = {
        "id": "",
        "start_date": date.today().isoformat(),
        "equipment_type_id": "",
        "equipment_model_name": "",
        "issue_type_id": "",
        "problem_description": "",
        "status_id": "",
        "completion_date": "",
        "due_date": "",
        "repair_parts": "",
        "master_id": "",
        "client_id": user.id if role == services.ROLE_CLIENT else "",
    }

    context = {
        "request": request,
        "active_page": "requests",
        "messages": [],
        "user": user,
        "role": role,
        "is_edit": False,
        "form_data": form_data,
        "field_errors": {},
        "statuses": lookups.statuses,
        "equipment_types": lookups.equipment_types,
        "issue_types": lookups.issue_types,
        "specialists": lookups.specialists,
        "clients": lookups.clients,
    }
    return templates.TemplateResponse("request_form.html", context)


@app.get("/ui/requests/{request_id}", response_class=HTMLResponse)
def ui_request_view(
    request_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            url="/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    req = db.get(models.RepairRequest, request_id)
    if not req:
        return RedirectResponse(
            url="/ui/requests?status=request_not_found",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not rbac.user_can_view_request(user=user, req=req):
        return RedirectResponse(
            url="/ui/requests?status=forbidden",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    comments = (
        db.query(models.RequestComment)
        .filter(models.RequestComment.request_id == request_id)
        .order_by(models.RequestComment.created_at.asc())
        .all()
    )

    help_open = (
        db.query(models.HelpRequest)
        .filter(models.HelpRequest.request_id == request_id)
        .filter(models.HelpRequest.status == "open")
        .order_by(models.HelpRequest.created_at.desc())
        .first()
    )

    can_create_help = (
        rbac.user_can_create_help_request(user)
        and req.master_id == user.id
    )

    context = {
        "request": request,
        "active_page": "requests",
        "messages": build_status_messages(request),
        "user": user,
        "role": rbac.role_name(user),
        "req": req,
        "comments": comments,
        "help_open": help_open,
        "can_edit": rbac.user_can_edit_request(user=user, req=req),
        "can_add_comment": rbac.user_can_add_comment(user=user, req=req),
        "can_delete": rbac.user_can_delete_request(user=user),
        "can_create_help": can_create_help,
    }
    return templates.TemplateResponse("request_view.html", context)


@app.get("/ui/requests/{request_id}/edit", response_class=HTMLResponse)
def ui_request_edit(
    request_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            url="/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    req = db.get(models.RepairRequest, request_id)
    if not req:
        return RedirectResponse(
            url="/ui/requests?status=request_not_found",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not rbac.user_can_edit_request(user=user, req=req):
        return RedirectResponse(
            url="/ui/requests?status=forbidden",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    lookups = services.load_request_form_lookups(db=db)

    form_data = {
        "id": req.id,
        "start_date": req.start_date.isoformat(),
        "equipment_type_id": req.equipment_model.equipment_type_id,
        "equipment_model_name": req.equipment_model.name,
        "issue_type_id": req.issue_type_id,
        "problem_description": req.problem_description,
        "status_id": req.status_id,
        "completion_date": req.completion_date.isoformat() if req.completion_date else "",
        "due_date": req.due_date.isoformat() if req.due_date else "",
        "repair_parts": req.repair_parts or "",
        "master_id": req.master_id,
        "client_id": req.client_id,
    }

    context = {
        "request": request,
        "active_page": "requests",
        "messages": [],
        "user": user,
        "role": rbac.role_name(user),
        "is_edit": True,
        "form_data": form_data,
        "field_errors": {},
        "statuses": lookups.statuses,
        "equipment_types": lookups.equipment_types,
        "issue_types": lookups.issue_types,
        "specialists": lookups.specialists,
        "clients": lookups.clients,
    }
    return templates.TemplateResponse("request_form.html", context)


@app.post("/ui/requests/save", response_class=HTMLResponse)
def ui_request_save(
    request: Request,
    id: str = Form(default=""),
    start_date_raw: str = Form(default="", alias="start_date"),
    equipment_type_id: str = Form(default=""),
    equipment_model_name: str = Form(default=""),
    issue_type_id: str = Form(default=""),
    problem_description: str = Form(default=""),
    status_id: str = Form(default=""),
    completion_date_raw: str = Form(default="", alias="completion_date"),
    due_date_raw: str = Form(default="", alias="due_date"),
    repair_parts: str = Form(default=""),
    master_id: str = Form(default=""),
    client_id: str = Form(default=""),
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            url="/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    role = rbac.role_name(user)
    is_edit = bool((id or "").strip())
    field_errors: dict[str, str] = {}

    start_date_val = parse_date(
        start_date_raw,
        field_errors,
        "start_date",
        "Дата добавления",
    )

    equip_type_id = parse_int(equipment_type_id)
    if not equip_type_id:
        field_errors["equipment_type_id"] = "Выберите тип техники."

    model_clean = (equipment_model_name or "").strip()
    if not model_clean:
        field_errors["equipment_model_name"] = "Укажите модель техники."

    problem_clean = (problem_description or "").strip()
    if not problem_clean:
        field_errors["problem_description"] = "Опишите проблему."

    st_id = parse_int(status_id)
    if role != services.ROLE_CLIENT and not st_id:
        field_errors["status_id"] = "Выберите статус заявки."

    completion_date_val: Optional[date] = None
    if (completion_date_raw or "").strip():
        completion_date_val = parse_date(
            completion_date_raw,
            field_errors,
            "completion_date",
            "Дата завершения",
        )

    due_date_val: Optional[date] = None
    if (due_date_raw or "").strip():
        due_date_val = parse_date(
            due_date_raw,
            field_errors,
            "due_date",
            "Плановый срок выполнения",
        )

    master_id_val = parse_int(master_id)
    client_id_val = parse_int(client_id)

    if role == services.ROLE_CLIENT:
        client_id_val = user.id

    if not client_id_val:
        field_errors["client_id"] = "Укажите заказчика."

    issue_type_val_id = parse_int(issue_type_id)

    if field_errors:
        lookups = services.load_request_form_lookups(db=db)

        form_data = {
            "id": (id or "").strip(),
            "start_date": (start_date_raw or "").strip(),
            "equipment_type_id": equip_type_id,
            "equipment_model_name": model_clean,
            "issue_type_id": issue_type_val_id or "",
            "problem_description": problem_clean,
            "status_id": st_id,
            "completion_date": (completion_date_raw or "").strip(),
            "due_date": (due_date_raw or "").strip(),
            "repair_parts": (repair_parts or "").strip(),
            "master_id": master_id_val or "",
            "client_id": client_id_val or "",
        }

        context = {
            "request": request,
            "active_page": "requests",
            "messages": [
                {
                    "type": "error",
                    "title": "Ошибка ввода данных",
                    "text": "Исправьте ошибки в форме и повторите попытку.",
                }
            ],
            "user": user,
            "role": role,
            "is_edit": is_edit,
            "form_data": form_data,
            "field_errors": field_errors,
            "statuses": lookups.statuses,
            "equipment_types": lookups.equipment_types,
            "issue_types": lookups.issue_types,
            "specialists": lookups.specialists,
            "clients": lookups.clients,
        }
        return templates.TemplateResponse(
            "request_form.html",
            context,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    request_input = usecases.RequestInput(
        id=parse_int(id) if is_edit else None,
        start_date=start_date_val,
        equipment_type_id=equip_type_id,
        equipment_model_name=model_clean,
        issue_type_id=issue_type_val_id,
        problem_description=problem_clean,
        status_id=st_id,
        completion_date=completion_date_val,
        due_date=due_date_val,
        repair_parts=(repair_parts or "").strip() or None,
        master_id=master_id_val,
        client_id=client_id_val,
    )

    try:
        usecases.save_request(db=db, user=user, data=request_input)
        db.commit()
    except usecases.DomainError as exc:
        db.rollback()
        code = getattr(exc, "code", "db_error")

        if code == "forbidden_status_change":
            target_url = f"/ui/requests/{request_input.id}?status={code}"
        elif code == "request_not_found":
            target_url = "/ui/requests?status=request_not_found"
        else:
            target_url = f"/ui/requests?status={code}"

        return RedirectResponse(
            url=target_url,
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except SQLAlchemyError:
        db.rollback()
        return RedirectResponse(
            url="/ui/requests?status=db_error",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    status_param = "request_updated" if is_edit else "request_created"
    return RedirectResponse(
        url=f"/ui/requests?status={status_param}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/ui/requests/{request_id}/delete")
def ui_request_delete(
    request_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            url="/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        usecases.delete_request(db=db, user=user, request_id=request_id)
        db.commit()
    except usecases.DomainError as exc:
        db.rollback()
        code = getattr(exc, "code", "db_error")
        return RedirectResponse(
            url=f"/ui/requests?status={code}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except SQLAlchemyError:
        db.rollback()
        return RedirectResponse(
            url="/ui/requests?status=db_error",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return RedirectResponse(
        url="/ui/requests?status=request_deleted",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/ui/requests/{request_id}/comment")
def ui_add_comment(
    request_id: int,
    request: Request,
    message: str = Form(default=""),
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            url="/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    msg_clean = (message or "").strip()
    if not msg_clean:
        return RedirectResponse(
            url=f"/ui/requests/{request_id}?status=comment_empty",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        usecases.add_comment(
            db=db,
            user=user,
            request_id=request_id,
            message=msg_clean,
        )
        db.commit()
    except usecases.DomainError as exc:
        db.rollback()
        code = getattr(exc, "code", "db_error")
        target = (
            f"/ui/requests/{request_id}?status={code}"
            if code != "request_not_found"
            else "/ui/requests?status=request_not_found"
        )
        return RedirectResponse(
            url=target,
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except SQLAlchemyError:
        db.rollback()
        return RedirectResponse(
            url=f"/ui/requests/{request_id}?status=db_error",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return RedirectResponse(
        url=f"/ui/requests/{request_id}?status=comment_added",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ===========================
# Help requests (assignment 3)
# ===========================


@app.get("/ui/requests/{request_id}/help/new", response_class=HTMLResponse)
def ui_help_request_new(
    request_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            "/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    req = db.get(models.RepairRequest, request_id)
    if not req:
        return RedirectResponse(
            "/ui/requests?status=request_not_found",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not (rbac.user_can_create_help_request(user) and req.master_id == user.id):
        return RedirectResponse(
            "/ui/requests?status=forbidden",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    context = {
        "request": request,
        "active_page": "requests",
        "messages": [],
        "user": user,
        "role": rbac.role_name(user),
        "req": req,
        "form_data": {"message": "", "proposed_due_date": ""},
        "field_errors": {},
    }
    return templates.TemplateResponse("help_request_form.html", context)


@app.post("/ui/requests/{request_id}/help/create")
def ui_help_request_create(
    request_id: int,
    request: Request,
    message: str = Form(default=""),
    proposed_due_date_raw: str = Form(default="", alias="proposed_due_date"),
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            "/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    req = db.get(models.RepairRequest, request_id)
    if not req:
        return RedirectResponse(
            "/ui/requests?status=request_not_found",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not (rbac.user_can_create_help_request(user) and req.master_id == user.id):
        return RedirectResponse(
            "/ui/requests?status=forbidden",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    field_errors: dict[str, str] = {}
    msg_clean = (message or "").strip()
    if not msg_clean:
        field_errors["message"] = "Опишите, какая помощь требуется."

    proposed_due_date: Optional[date] = None
    if (proposed_due_date_raw or "").strip():
        proposed_due_date = parse_date(
            proposed_due_date_raw,
            field_errors,
            "proposed_due_date",
            "Предлагаемый срок",
        )

    if field_errors:
        context = {
            "request": request,
            "active_page": "requests",
            "messages": [
                {
                    "type": "error",
                    "title": "Ошибка ввода данных",
                    "text": "Исправьте ошибки в форме и повторите попытку.",
                }
            ],
            "user": user,
            "role": rbac.role_name(user),
            "req": req,
            "form_data": {
                "message": msg_clean,
                "proposed_due_date": (proposed_due_date_raw or "").strip(),
            },
            "field_errors": field_errors,
        }
        return templates.TemplateResponse(
            "help_request_form.html",
            context,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        usecases.create_help_request(
            db=db,
            user=user,
            data=usecases.HelpRequestCreateInput(
                request_id=request_id,
                message=msg_clean,
                proposed_due_date=proposed_due_date,
            ),
        )
        db.commit()
    except usecases.DomainError as exc:
        db.rollback()
        return RedirectResponse(
            f"/ui/requests/{request_id}?status={exc.code}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except SQLAlchemyError:
        db.rollback()
        return RedirectResponse(
            f"/ui/requests/{request_id}?status=db_error",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return RedirectResponse(
        f"/ui/requests/{request_id}?status=help_created",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/ui/quality", response_class=HTMLResponse)
def ui_quality_desk(
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            "/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not rbac.user_can_view_quality_desk(user):
        return RedirectResponse(
            "/ui/requests?status=forbidden",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    open_help = (
        db.query(models.HelpRequest)
        .filter(models.HelpRequest.status == "open")
        .order_by(models.HelpRequest.created_at.desc())
        .all()
    )
    overdue = services.get_overdue_requests(db=db)

    context = {
        "request": request,
        "active_page": "quality",
        "messages": build_status_messages(request),
        "user": user,
        "role": rbac.role_name(user),
        "open_help": open_help,
        "overdue_requests": overdue,
    }
    return templates.TemplateResponse("quality_desk.html", context)


@app.get("/ui/help/{help_id}", response_class=HTMLResponse)
def ui_help_request_view(
    help_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            "/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not rbac.user_can_handle_help_request(user):
        return RedirectResponse(
            "/ui/requests?status=forbidden",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    help_req = db.get(models.HelpRequest, help_id)
    if not help_req:
        return RedirectResponse(
            "/ui/quality?status=help_not_found",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    req = db.get(models.RepairRequest, help_req.request_id)
    if not req:
        return RedirectResponse(
            "/ui/quality?status=request_not_found",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    masters = (
        db.query(models.User)
        .join(models.UserRole)
        .filter(models.UserRole.name.in_([services.ROLE_MASTER, services.ROLE_SPECIALIST]))
        .order_by(models.User.fio)
        .all()
    )

    context = {
        "request": request,
        "active_page": "quality",
        "messages": build_status_messages(request),
        "user": user,
        "role": rbac.role_name(user),
        "help_req": help_req,
        "req": req,
        "masters": masters,
        "form_data": {"resolution_note": "", "assigned_master_id": "", "new_due_date": ""},
        "field_errors": {},
    }
    return templates.TemplateResponse("help_request_view.html", context)


@app.post("/ui/help/{help_id}/close")
def ui_help_request_close(
    help_id: int,
    request: Request,
    resolution_note: str = Form(default=""),
    assigned_master_id: str = Form(default=""),
    new_due_date_raw: str = Form(default="", alias="new_due_date"),
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            "/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not rbac.user_can_handle_help_request(user):
        return RedirectResponse(
            "/ui/requests?status=forbidden",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    help_req = db.get(models.HelpRequest, help_id)
    if not help_req:
        return RedirectResponse(
            "/ui/quality?status=help_not_found",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    req = db.get(models.RepairRequest, help_req.request_id)
    if not req:
        return RedirectResponse(
            "/ui/quality?status=request_not_found",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    field_errors: dict[str, str] = {}

    new_due_date: Optional[date] = None
    if (new_due_date_raw or "").strip():
        new_due_date = parse_date(
            new_due_date_raw,
            field_errors,
            "new_due_date",
            "Новый срок",
        )
        if new_due_date and new_due_date < req.start_date:
            field_errors["new_due_date"] = "Новый срок не может быть раньше даты добавления заявки."

    assigned_master_id_val = parse_int(assigned_master_id)

    if field_errors:
        masters = (
            db.query(models.User)
            .join(models.UserRole)
            .filter(models.UserRole.name.in_([services.ROLE_MASTER, services.ROLE_SPECIALIST]))
            .order_by(models.User.fio)
            .all()
        )

        context = {
            "request": request,
            "active_page": "quality",
            "messages": [
                {
                    "type": "error",
                    "title": "Ошибка ввода данных",
                    "text": "Исправьте ошибки в форме и повторите попытку.",
                }
            ],
            "user": user,
            "role": rbac.role_name(user),
            "help_req": help_req,
            "req": req,
            "masters": masters,
            "form_data": {
                "resolution_note": (resolution_note or "").strip(),
                "assigned_master_id": assigned_master_id_val or "",
                "new_due_date": (new_due_date_raw or "").strip(),
            },
            "field_errors": field_errors,
        }
        return templates.TemplateResponse(
            "help_request_view.html",
            context,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        usecases.close_help_request(
            db=db,
            user=user,
            data=usecases.HelpRequestCloseInput(
                help_id=help_id,
                resolution_note=(resolution_note or "").strip(),
                assigned_master_id=assigned_master_id_val,
                new_due_date=new_due_date,
            ),
        )
        db.commit()
    except usecases.DomainError as exc:
        db.rollback()
        return RedirectResponse(
            f"/ui/quality?status={exc.code}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except SQLAlchemyError:
        db.rollback()
        return RedirectResponse(
            "/ui/quality?status=db_error",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return RedirectResponse(
        "/ui/quality?status=help_closed",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ===========================
# Users (manager only)
# ===========================


@app.get("/ui/users", response_class=HTMLResponse)
def ui_users_list(
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            "/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not rbac.user_can_manage_users(user):
        return RedirectResponse(
            "/ui/requests?status=forbidden",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    users = (
        db.query(models.User)
        .join(models.UserRole)
        .order_by(models.User.fio)
        .all()
    )

    context = {
        "request": request,
        "active_page": "users",
        "messages": build_status_messages(request),
        "user": user,
        "role": rbac.role_name(user),
        "users": users,
    }
    return templates.TemplateResponse("users.html", context)


@app.get("/ui/users/new", response_class=HTMLResponse)
def ui_user_new(
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            "/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not rbac.user_can_manage_users(user):
        return RedirectResponse(
            "/ui/requests?status=forbidden",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    roles = db.query(models.UserRole).order_by(models.UserRole.name).all()

    form_data = {
        "id": "",
        "fio": "",
        "phone": "",
        "login": "",
        "role_id": "",
        "password": "",
        "password_repeat": "",
    }

    context = {
        "request": request,
        "active_page": "users",
        "messages": [],
        "user": user,
        "role": rbac.role_name(user),
        "is_edit": False,
        "form_data": form_data,
        "field_errors": {},
        "roles": roles,
    }
    return templates.TemplateResponse("user_form.html", context)


@app.get("/ui/users/{user_id}/edit", response_class=HTMLResponse)
def ui_user_edit(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            "/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not rbac.user_can_manage_users(user):
        return RedirectResponse(
            "/ui/requests?status=forbidden",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    target = db.get(models.User, user_id)
    if not target:
        return RedirectResponse(
            "/ui/users?status=user_not_found",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    roles = db.query(models.UserRole).order_by(models.UserRole.name).all()

    form_data = {
        "id": target.id,
        "fio": target.fio,
        "phone": target.phone,
        "login": target.login,
        "role_id": target.role_id,
        "password": "",
        "password_repeat": "",
    }

    context = {
        "request": request,
        "active_page": "users",
        "messages": [],
        "user": user,
        "role": rbac.role_name(user),
        "is_edit": True,
        "form_data": form_data,
        "field_errors": {},
        "roles": roles,
    }
    return templates.TemplateResponse("user_form.html", context)


@app.post("/ui/users/save", response_class=HTMLResponse)
def ui_user_save(
    request: Request,
    id: str = Form(default=""),
    fio: str = Form(default=""),
    phone: str = Form(default=""),
    login: str = Form(default=""),
    password: str = Form(default=""),
    password_repeat: str = Form(default=""),
    role_id: str = Form(default=""),
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            "/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not rbac.user_can_manage_users(user):
        return RedirectResponse(
            "/ui/requests?status=forbidden",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    is_edit = bool((id or "").strip())
    field_errors: dict[str, str] = {}

    fio_clean = (fio or "").strip()
    phone_clean = (phone or "").strip()
    login_clean = (login or "").strip()
    role_id_val = parse_int(role_id)

    if not fio_clean:
        field_errors["fio"] = "Укажите ФИО пользователя."

    if not phone_clean:
        field_errors["phone"] = "Укажите номер телефона."

    if not login_clean:
        field_errors["login"] = "Укажите логин."

    if not role_id_val:
        field_errors["role_id"] = "Выберите роль пользователя."

    password_clean = (password or "").strip()
    password_repeat_clean = (password_repeat or "").strip()

    if not is_edit:
        if not password_clean:
            field_errors["password"] = "Для нового пользователя необходимо задать пароль."
        elif password_clean != password_repeat_clean:
            field_errors["password_repeat"] = "Пароли не совпадают."
    else:
        if password_clean or password_repeat_clean:
            if password_clean != password_repeat_clean:
                field_errors["password_repeat"] = "Пароли не совпадают."

    roles = db.query(models.UserRole).order_by(models.UserRole.name).all()

    if field_errors:
        form_data = {
            "id": (id or "").strip(),
            "fio": fio_clean,
            "phone": phone_clean,
            "login": login_clean,
            "role_id": role_id_val or "",
            "password": "",
            "password_repeat": "",
        }
        context = {
            "request": request,
            "active_page": "users",
            "messages": [
                {
                    "type": "error",
                    "title": "Ошибка ввода данных",
                    "text": "Исправьте ошибки в форме и повторите попытку.",
                }
            ],
            "user": user,
            "role": rbac.role_name(user),
            "is_edit": is_edit,
            "form_data": form_data,
            "field_errors": field_errors,
            "roles": roles,
        }
        return templates.TemplateResponse(
            "user_form.html",
            context,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    existing_user: Optional[models.User] = None
    if is_edit:
        user_id = parse_int(id)
        if not user_id:
            return RedirectResponse(
                "/ui/users?status=user_not_found",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        existing_user = db.get(models.User, user_id)
        if not existing_user:
            return RedirectResponse(
                "/ui/users?status=user_not_found",
                status_code=status.HTTP_303_SEE_OTHER,
            )

    login_q = db.query(models.User).filter(models.User.login == login_clean)
    if is_edit and existing_user:
        login_q = login_q.filter(models.User.id != existing_user.id)

    if login_q.first():
        form_data = {
            "id": (id or "").strip(),
            "fio": fio_clean,
            "phone": phone_clean,
            "login": login_clean,
            "role_id": role_id_val or "",
            "password": "",
            "password_repeat": "",
        }
        context = {
            "request": request,
            "active_page": "users",
            "messages": [
                {
                    "type": "error",
                    "title": "Ошибка ввода данных",
                    "text": "Пользователь с таким логином уже существует.",
                }
            ],
            "user": user,
            "role": rbac.role_name(user),
            "is_edit": is_edit,
            "form_data": form_data,
            "field_errors": {"login": "Логин должен быть уникальным."},
            "roles": roles,
        }
        return templates.TemplateResponse(
            "user_form.html",
            context,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if is_edit and existing_user:
        target = existing_user
    else:
        target = models.User()
        db.add(target)

    target.fio = fio_clean
    target.phone = phone_clean
    target.login = login_clean
    target.role_id = int(role_id_val)

    if password_clean:
        target.password_hash = services.hash_password(password_clean)

    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return RedirectResponse(
            "/ui/users?status=db_error",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    code = "user_updated" if is_edit else "user_created"
    return RedirectResponse(
        f"/ui/users?status={code}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/ui/users/{user_id}/delete")
def ui_user_delete(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            "/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not rbac.user_can_manage_users(user):
        return RedirectResponse(
            "/ui/requests?status=forbidden",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    target = db.get(models.User, user_id)
    if not target:
        return RedirectResponse(
            "/ui/users?status=user_not_found",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        db.delete(target)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return RedirectResponse(
            "/ui/users?status=user_delete_failed",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return RedirectResponse(
        "/ui/users?status=user_deleted",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ===========================
# QR + Statistics
# ===========================


@app.get("/ui/requests/{request_id}/qr")
def ui_request_qr(
    request_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            "/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    req = db.get(models.RepairRequest, request_id)
    if not req:
        return RedirectResponse(
            "/ui/requests?status=request_not_found",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    survey_url = services.build_quality_survey_url(request_id=req.id)

    img = qrcode.make(survey_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return StreamingResponse(buf, media_type="image/png")


@app.get("/ui/statistics", response_class=HTMLResponse)
def ui_statistics(
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request=request, db=db)
    if not user:
        return RedirectResponse(
            "/ui/login?status=login_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not rbac.user_can_view_statistics(user):
        return RedirectResponse(
            "/ui/requests?status=forbidden",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    stats = services.calculate_statistics(db=db)

    context = {
        "request": request,
        "active_page": "statistics",
        "messages": build_status_messages(request),
        "user": user,
        "role": rbac.role_name(user),
        "stats": stats,
    }
    return templates.TemplateResponse("statistics.html", context)


@app.get("/health")
def health():
    return {"ok": True}