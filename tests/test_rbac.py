from app import models, rbac, services


def make_user(role_name: str, user_id: int = 1) -> models.User:
    role = models.UserRole(id=1, name=role_name)
    user = models.User(
        id=user_id,
        fio="Test User",
        phone="000",
        login=f"user{user_id}",
        password_hash="x",
        role_id=role.id,
    )
    user.role = role
    return user


def make_request(client_id: int, master_id: int, is_final: bool) -> models.RepairRequest:
    status = models.RequestStatus(id=1, name="Статус", is_final=is_final)
    req = models.RepairRequest(
        id=10,
        start_date=None,
        equipment_model_id=1,
        issue_type_id=1,
        problem_description="",
        status_id=status.id,
        completion_date=None,
        repair_parts=None,
        master_id=master_id,
        client_id=client_id,
    )
    req.status = status
    return req


def test_manager_can_view_any_request():
    manager = make_user(services.ROLE_MANAGER)
    req = make_request(client_id=100, master_id=200, is_final=False)

    assert rbac.user_can_view_request(manager, req) is True


def test_client_can_view_only_own_request():
    client = make_user(services.ROLE_CLIENT, user_id=5)
    own_req = make_request(client_id=5, master_id=10, is_final=False)
    foreign_req = make_request(client_id=6, master_id=10, is_final=False)

    assert rbac.user_can_view_request(client, own_req) is True
    assert rbac.user_can_view_request(client, foreign_req) is False


def test_master_cannot_reopen_final_request():
    master = make_user(services.ROLE_MASTER, user_id=7)

    old_status = models.RequestStatus(id=1, name="Завершена", is_final=True)
    new_status = models.RequestStatus(id=2, name="В работе", is_final=False)

    assert (
        rbac.user_can_change_status(
            user=master,
            old_status=old_status,
            new_status=new_status,
        )
        is False
    )


def test_manager_can_change_status_any_to_any():
    manager = make_user(services.ROLE_MANAGER)

    s1 = models.RequestStatus(id=1, name="Новая", is_final=False)
    s2 = models.RequestStatus(id=2, name="Завершена", is_final=True)

    assert rbac.user_can_change_status(manager, s1, s2) is True
    assert rbac.user_can_change_status(manager, s2, s1) is True