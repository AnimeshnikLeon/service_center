from datetime import date
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class UserRole_out(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class User_out(BaseModel):
    id: int
    fio: str
    phone: str
    login: str
    role: UserRole_out

    class Config:
        from_attributes = True


class RequestStatus_out(BaseModel):
    id: int
    name: str
    is_final: bool

    class Config:
        from_attributes = True


class EquipmentType_out(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class EquipmentModel_out(BaseModel):
    id: int
    name: str
    equipment_type: EquipmentType_out

    class Config:
        from_attributes = True


class IssueType_out(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class RepairRequest_out(BaseModel):
    id: int
    start_date: date
    equipment_model: EquipmentModel_out
    issue_type: IssueType_out
    problem_description: str
    status: RequestStatus_out
    completion_date: Optional[date]
    due_date: Optional[date]
    repair_parts: Optional[str]
    master: Optional[User_out]
    client: User_out
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class Comment_out(BaseModel):
    id: int
    message: str
    created_at: datetime
    master: User_out

    class Config:
        from_attributes = True


class Statistics_out(BaseModel):
    total_requests: int
    completed_requests: int
    average_repair_time_days: Optional[float]
    by_equipment_type: dict[str, int]
    by_issue_type: dict[str, int]