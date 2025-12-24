import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy import text

from app.services import hash_password
from app.services import normalize_issue_type_name


db_url = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB')}"
)

engine = create_engine(db_url, echo=False, future=True)

root = Path(__file__).resolve().parent
data_dir = Path("/app/data") if Path("/app/data").exists() else root.parent / "data"
import_dir = data_dir / "import"


def parse_nullable_date(value: str) -> Optional[str]:
    raw = (value or "").strip()
    if not raw or raw.lower() == "null":
        return None
    try:
        datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None
    return raw


def parse_nullable_int(value: str) -> Optional[int]:
    raw = (value or "").strip()
    if not raw or raw.lower() == "null":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def read_csv(path: Path):
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        return list(reader)


def ensure_roles(conn):
    roles = [
        "Менеджер",
        "Оператор",
        "Мастер",
        "Специалист",
        "Заказчик",
        "Менеджер по качеству",
    ]
    for r in roles:
        conn.execute(
            text(
                """
                INSERT INTO user_role (name)
                VALUES (:name)
                ON CONFLICT (name) DO NOTHING
                """
            ),
            {"name": r},
        )


def ensure_statuses(conn):
    statuses = [
        ("Новая заявка", False),
        ("В процессе ремонта", False),
        ("Ожидание комплектующих", False),
        ("Готова к выдаче", True),
        ("Завершена", True),
    ]
    for name, is_final in statuses:
        conn.execute(
            text(
                """
                INSERT INTO request_status (name, is_final)
                VALUES (:name, :is_final)
                ON CONFLICT (name) DO UPDATE SET is_final = EXCLUDED.is_final
                """
            ),
            {"name": name, "is_final": is_final},
        )


def ensure_equipment_types(conn, requests_rows):
    values = set()
    for r in requests_rows:
        values.add((r.get("homeTechType") or "").strip())
    for name in sorted(v for v in values if v):
        conn.execute(
            text(
                """
                INSERT INTO equipment_type (name)
                VALUES (:name)
                ON CONFLICT (name) DO NOTHING
                """
            ),
            {"name": name},
        )


def ensure_issue_types(conn, requests_rows):
    values = set()
    for r in requests_rows:
        values.add(normalize_issue_type_name(r.get("problemDescryption") or ""))
    for name in sorted(v for v in values if v):
        conn.execute(
            text(
                """
                INSERT INTO issue_type (name)
                VALUES (:name)
                ON CONFLICT (name) DO NOTHING
                """
            ),
            {"name": name},
        )


def ensure_equipment_models(conn, requests_rows):
    pairs = set()
    for r in requests_rows:
        eq_type = (r.get("homeTechType") or "").strip()
        model = (r.get("homeTechModel") or "").strip()
        if eq_type and model:
            pairs.add((eq_type, model))

    for eq_type, model in sorted(pairs):
        eq_type_id = conn.execute(
            text("SELECT id FROM equipment_type WHERE name = :n"),
            {"n": eq_type},
        ).scalar_one()

        conn.execute(
            text(
                """
                INSERT INTO equipment_model (equipment_type_id, name)
                VALUES (:equipment_type_id, :name)
                ON CONFLICT (equipment_type_id, name) DO NOTHING
                """
            ),
            {"equipment_type_id": eq_type_id, "name": model},
        )


def import_users(conn, users_rows):
    for row in users_rows:
        fio = (row.get("fio") or "").strip()
        phone = (row.get("phone") or "").strip()
        login = (row.get("login") or "").strip()
        password = (row.get("password") or "").strip()
        role_name = (row.get("type") or "").strip()

        if not (fio and phone and login and password and role_name):
            continue

        role_id = conn.execute(
            text("SELECT id FROM user_role WHERE name = :n"),
            {"n": role_name},
        ).scalar_one()

        password_hash = hash_password(password=password)

        conn.execute(
            text(
                """
                INSERT INTO app_user (id, fio, phone, login, password_hash, role_id)
                VALUES (:id, :fio, :phone, :login, :password_hash, :role_id)
                ON CONFLICT (id) DO UPDATE
                SET fio = EXCLUDED.fio,
                    phone = EXCLUDED.phone,
                    login = EXCLUDED.login,
                    password_hash = EXCLUDED.password_hash,
                    role_id = EXCLUDED.role_id
                """
            ),
            {
                "id": int(row.get("userID")),
                "fio": fio,
                "phone": phone,
                "login": login,
                "password_hash": password_hash,
                "role_id": role_id,
            },
        )


def get_or_create_spare_part_id(conn, part_name: str) -> int:
    cleaned = (part_name or "").strip()
    if not cleaned:
        raise ValueError("part_name is empty")

    conn.execute(
        text(
            """
            INSERT INTO spare_part (name)
            VALUES (:name)
            ON CONFLICT (name) DO NOTHING
            """
        ),
        {"name": cleaned},
    )

    part_id = conn.execute(
        text("SELECT id FROM spare_part WHERE name = :name"),
        {"name": cleaned},
    ).scalar_one()

    return int(part_id)


def import_request_spare_parts(conn, request_id: int, repair_parts_raw: Optional[str]) -> None:
    raw = (repair_parts_raw or "").strip()
    if not raw:
        return

    chunks = [raw]
    if "\n" in raw:
        chunks = [c.strip() for c in raw.splitlines() if c.strip()]
    elif ";" in raw:
        chunks = [c.strip() for c in raw.split(";") if c.strip()]

    for part_name in chunks:
        part_id = get_or_create_spare_part_id(conn, part_name)

        conn.execute(
            text(
                """
                INSERT INTO request_spare_part (request_id, spare_part_id, quantity, note)
                VALUES (:request_id, :spare_part_id, 1, NULL)
                ON CONFLICT (request_id, spare_part_id) DO NOTHING
                """
            ),
            {
                "request_id": int(request_id),
                "spare_part_id": int(part_id),
            },
        )


def import_requests(conn, requests_rows):
    for row in requests_rows:
        start_date = parse_nullable_date(row.get("startDate"))
        equipment_type = (row.get("homeTechType") or "").strip()
        equipment_model_name = (row.get("homeTechModel") or "").strip()
        problem = (row.get("problemDescryption") or "").strip()
        status_name = (row.get("requestStatus") or "").strip()
        completion_date = parse_nullable_date(row.get("completionDate"))
        repair_parts_raw = (row.get("repairParts") or "").strip()
        repair_parts_legacy = repair_parts_raw or None

        master_src_id = parse_nullable_int(row.get("masterID"))
        client_src_id = parse_nullable_int(row.get("clientID"))

        if not (start_date and equipment_type and equipment_model_name and problem and status_name and client_src_id):
            continue

        equipment_type_id = conn.execute(
            text("SELECT id FROM equipment_type WHERE name = :n"),
            {"n": equipment_type},
        ).scalar_one()

        equipment_model_id = conn.execute(
            text(
                """
                SELECT id
                FROM equipment_model
                WHERE equipment_type_id = :equipment_type_id
                  AND name = :name
                """
            ),
            {"equipment_type_id": equipment_type_id, "name": equipment_model_name},
        ).scalar_one()

        issue_type_name = normalize_issue_type_name(problem)
        issue_type_id = conn.execute(
            text("SELECT id FROM issue_type WHERE name = :n"),
            {"n": issue_type_name},
        ).scalar_one()

        status_id = conn.execute(
            text("SELECT id FROM request_status WHERE name = :n"),
            {"n": status_name},
        ).scalar_one()

        client_id = conn.execute(
            text("SELECT id FROM app_user WHERE id = :id"),
            {"id": client_src_id},
        ).scalar_one()

        master_id: Optional[int] = None
        if master_src_id is not None:
            master_id = conn.execute(
                text("SELECT id FROM app_user WHERE id = :id"),
                {"id": master_src_id},
            ).scalar_one_or_none()

        request_id = int(row.get("requestID"))

        conn.execute(
            text(
                """
                INSERT INTO repair_request (
                    id, start_date, equipment_model_id, issue_type_id,
                    problem_description, status_id, completion_date,
                    repair_parts, master_id, client_id
                )
                VALUES (
                    :id, :start_date, :equipment_model_id, :issue_type_id,
                    :problem_description, :status_id, :completion_date,
                    :repair_parts, :master_id, :client_id
                )
                ON CONFLICT (id) DO UPDATE
                SET start_date = EXCLUDED.start_date,
                    equipment_model_id = EXCLUDED.equipment_model_id,
                    issue_type_id = EXCLUDED.issue_type_id,
                    problem_description = EXCLUDED.problem_description,
                    status_id = EXCLUDED.status_id,
                    completion_date = EXCLUDED.completion_date,
                    repair_parts = EXCLUDED.repair_parts,
                    master_id = EXCLUDED.master_id,
                    client_id = EXCLUDED.client_id
                """
            ),
            {
                "id": request_id,
                "start_date": start_date,
                "equipment_model_id": equipment_model_id,
                "issue_type_id": issue_type_id,
                "problem_description": problem,
                "status_id": status_id,
                "completion_date": completion_date,
                "repair_parts": repair_parts_legacy,
                "master_id": master_id,
                "client_id": client_id,
            },
        )

        import_request_spare_parts(
            conn=conn,
            request_id=request_id,
            repair_parts_raw=repair_parts_raw,
        )


def import_comments(conn, comments_rows):
    for row in comments_rows:
        message = (row.get("message") or "").strip()
        master_id = parse_nullable_int(row.get("masterID"))
        request_id = parse_nullable_int(row.get("requestID"))

        if not (message and master_id and request_id):
            continue

        conn.execute(
            text(
                """
                INSERT INTO request_comment (id, request_id, master_id, message)
                VALUES (:id, :request_id, :master_id, :message)
                ON CONFLICT (id) DO UPDATE
                SET request_id = EXCLUDED.request_id,
                    master_id = EXCLUDED.master_id,
                    message = EXCLUDED.message
                """
            ),
            {
                "id": int(row.get("commentID")),
                "request_id": request_id,
                "master_id": master_id,
                "message": message,
            },
        )


def sync_sequences(conn):
    tables = [
        "app_user",
        "repair_request",
        "request_comment",
        "spare_part",
        "request_spare_part",
    ]

    for table in tables:
        sql = f"""
            SELECT setval(
                pg_get_serial_sequence('{table}', 'id'),
                COALESCE((SELECT MAX(id) FROM {table}), 0),
                true
            )
        """
        conn.execute(text(sql))


def main():
    users_path = import_dir / "inputDataUsers.csv"
    requests_path = import_dir / "inputDataRequests.csv"
    comments_path = import_dir / "inputDataComments.csv"

    users_rows = read_csv(users_path)
    requests_rows = read_csv(requests_path)
    comments_rows = read_csv(comments_path)

    with engine.begin() as conn:
        ensure_roles(conn=conn)
        ensure_statuses(conn=conn)
        ensure_equipment_types(conn=conn, requests_rows=requests_rows)
        ensure_issue_types(conn=conn, requests_rows=requests_rows)
        ensure_equipment_models(conn=conn, requests_rows=requests_rows)

        import_users(conn=conn, users_rows=users_rows)
        import_requests(conn=conn, requests_rows=requests_rows)
        import_comments(conn=conn, comments_rows=comments_rows)

        sync_sequences(conn=conn)

    print("Import finished.")


if __name__ == "__main__":
    main()