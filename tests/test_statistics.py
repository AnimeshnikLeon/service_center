from datetime import date

from app.services import RequestRow
from app.services import calculate_statistics_from_rows


def test_statistics_average_repair_time_days():
    rows = [
        RequestRow(
            start_date=date(2023, 1, 1),
            completion_date=date(2023, 1, 6),
            status_is_final=True,
            equipment_type="Кондиционер",
            issue_type="Не охлаждает",
        ),
        RequestRow(
            start_date=date(2023, 1, 10),
            completion_date=date(2023, 1, 11),
            status_is_final=True,
            equipment_type="Кондиционер",
            issue_type="Шумит",
        ),
        RequestRow(
            start_date=date(2023, 2, 1),
            completion_date=None,
            status_is_final=False,
            equipment_type="Увлажнитель",
            issue_type="Запах",
        ),
    ]

    stats = calculate_statistics_from_rows(rows)

    assert stats["total_requests"] == 3
    assert stats["completed_requests"] == 2
    assert stats["average_repair_time_days"] == 3.0