from datetime import date

import pytest

from app import models, services, usecases


def make_role(name: str) -> models.UserRole:
    return models.UserRole(id=1, name=name)


def make_user(user_id: int, role_name: str) -> models.User:
    u = models.User(
        id=user_id,
        fio="User",
        phone="000",
        login=f"u{user_id}",
        password_hash="x",
        role_id=1,
    )
    u.role = make_role(role_name)
    return u


class FakeQuery:
    def __init__(self, first_obj=None):
        self._first_obj = first_obj

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._first_obj


class FakeSession:
    def __init__(self, by_id: dict[tuple[type, int], object], open_help_exists: bool = False):
        self._by_id = by_id
        self._added = []
        self._open_help_exists = open_help_exists

    def get(self, model, obj_id):
        return self._by_id.get((model, int(obj_id)))

    def query(self, model):
        if model is models.HelpRequest:
            return FakeQuery(first_obj=(object() if self._open_help_exists else None))
        return FakeQuery(first_obj=None)

    def add(self, obj):
        self._added.append(obj)


def test_master_can_create_help_request_for_own_request():
    master = make_user(2, services.ROLE_MASTER)
    req = models.RepairRequest(
        id=10,
        start_date=date(2023, 1, 1),
        equipment_model_id=1,
        issue_type_id=1,
        problem_description="x",
        status_id=1,
        completion_date=None,
        due_date=None,
        repair_parts=None,
        master_id=2,
        client_id=7,
    )
    req.status = models.RequestStatus(id=1, name="В работе", is_final=False)

    db = FakeSession(by_id={(models.RepairRequest, 10): req}, open_help_exists=False)

    created = usecases.create_help_request(
        db=db,
        user=master,
        data=usecases.HelpRequestCreateInput(request_id=10, message="Нужна помощь", proposed_due_date=None),
    )

    assert created.request_id == 10
    assert created.created_by_master_id == 2
    assert created.status == "open"


def test_master_cannot_create_help_request_for_foreign_request():
    master = make_user(2, services.ROLE_MASTER)
    req = models.RepairRequest(
        id=10,
        start_date=date(2023, 1, 1),
        equipment_model_id=1,
        issue_type_id=1,
        problem_description="x",
        status_id=1,
        completion_date=None,
        due_date=None,
        repair_parts=None,
        master_id=99,
        client_id=7,
    )
    req.status = models.RequestStatus(id=1, name="В работе", is_final=False)

    db = FakeSession(by_id={(models.RepairRequest, 10): req}, open_help_exists=False)

    with pytest.raises(usecases.PermissionDeniedError):
        usecases.create_help_request(
            db=db,
            user=master,
            data=usecases.HelpRequestCreateInput(request_id=10, message="Нужна помощь", proposed_due_date=None),
        )


def test_duplicate_open_help_request_is_blocked():
    master = make_user(2, services.ROLE_MASTER)
    req = models.RepairRequest(
        id=10,
        start_date=date(2023, 1, 1),
        equipment_model_id=1,
        issue_type_id=1,
        problem_description="x",
        status_id=1,
        completion_date=None,
        due_date=None,
        repair_parts=None,
        master_id=2,
        client_id=7,
    )
    req.status = models.RequestStatus(id=1, name="В работе", is_final=False)

    db = FakeSession(by_id={(models.RepairRequest, 10): req}, open_help_exists=True)

    with pytest.raises(usecases.HelpRequestAlreadyOpenError):
        usecases.create_help_request(
            db=db,
            user=master,
            data=usecases.HelpRequestCreateInput(request_id=10, message="Нужна помощь", proposed_due_date=None),
        )