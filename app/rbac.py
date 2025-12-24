from typing import Optional

from . import models
from . import services


def role_name(user: Optional[models.User]) -> str:
    if not user:
        return ""
    if not user.role:
        return ""
    return user.role.name


def user_can_create_request(user: models.User) -> bool:
    r = role_name(user)
    return r in (
        services.ROLE_MANAGER,
        services.ROLE_OPERATOR,
        services.ROLE_QUALITY_MANAGER,
        services.ROLE_CLIENT,
    )


def user_can_view_request(user: models.User, req: models.RepairRequest) -> bool:
    r = role_name(user)

    if r in (
        services.ROLE_MANAGER,
        services.ROLE_OPERATOR,
        services.ROLE_QUALITY_MANAGER,
    ):
        return True

    if services.is_master_role(r):
        return req.master_id == user.id

    if r == services.ROLE_CLIENT:
        return req.client_id == user.id

    return False


def user_can_edit_request(user: models.User, req: models.RepairRequest) -> bool:
    r = role_name(user)

    if r in (
        services.ROLE_MANAGER,
        services.ROLE_OPERATOR,
        services.ROLE_QUALITY_MANAGER,
    ):
        return True

    if services.is_master_role(r):
        return req.master_id == user.id

    if r == services.ROLE_CLIENT:
        return req.client_id == user.id and not bool(req.status.is_final)

    return False


def user_can_delete_request(user: models.User) -> bool:
    r = role_name(user)
    return r in (services.ROLE_MANAGER, services.ROLE_OPERATOR)


def user_can_add_comment(user: models.User, req: models.RepairRequest) -> bool:
    r = role_name(user)
    return services.is_master_role(r) and req.master_id == user.id


def user_can_assign_master(user: models.User) -> bool:
    r = role_name(user)
    return r in (
        services.ROLE_MANAGER,
        services.ROLE_OPERATOR,
        services.ROLE_QUALITY_MANAGER,
    )


def user_can_change_status(
    user: models.User,
    old_status: models.RequestStatus,
    new_status: models.RequestStatus,
) -> bool:
    r = role_name(user)

    if r in (
        services.ROLE_MANAGER,
        services.ROLE_OPERATOR,
        services.ROLE_QUALITY_MANAGER,
    ):
        return True

    if services.is_master_role(r):
        if old_status.id == new_status.id:
            return True
        if old_status.is_final and not new_status.is_final:
            return False
        return True

    if r == services.ROLE_CLIENT:
        return old_status.id == new_status.id

    return False


def user_can_manage_users(user: models.User) -> bool:
    return role_name(user) == services.ROLE_MANAGER


def user_can_view_statistics(user: models.User) -> bool:
    return role_name(user) == services.ROLE_MANAGER


def user_can_view_quality_desk(user: models.User) -> bool:
    return role_name(user) in (services.ROLE_QUALITY_MANAGER, services.ROLE_MANAGER)


def user_can_create_help_request(user: models.User) -> bool:
    return services.is_master_role(role_name(user))


def user_can_handle_help_request(user: models.User) -> bool:
    return role_name(user) in (services.ROLE_QUALITY_MANAGER, services.ROLE_MANAGER)