-- Набор запросов и представлений для отчетов (Задание 2)
-- Файл можно запускать многократно: используются CREATE OR REPLACE VIEW.

-- =========================================================
-- Отчет 1: Список заявок с деталями (для печати/выгрузки)
-- =========================================================

CREATE OR REPLACE VIEW v_request_full AS
SELECT
    rr.id                    AS request_id,
    rr.start_date            AS start_date,
    et.name                  AS equipment_type,
    em.name                  AS equipment_model,
    it.name                  AS issue_type,
    rr.problem_description   AS problem_description,
    rs.name                  AS status,
    rs.is_final              AS status_is_final,
    rr.completion_date       AS completion_date,
    rr.due_date              AS due_date,
    CASE
        WHEN rr.due_date IS NOT NULL AND rs.is_final = FALSE AND rr.due_date < CURRENT_DATE THEN TRUE
        ELSE FALSE
    END AS is_overdue,
    rr.repair_parts          AS repair_parts_legacy,
    COALESCE(parts.parts_list, '') AS parts_list,
    master_user.id           AS master_id,
    master_user.fio          AS master_fio,
    client_user.id           AS client_id,
    client_user.fio          AS client_fio,
    client_user.phone        AS client_phone,
    rr.created_at            AS created_at,
    rr.updated_at            AS updated_at
FROM repair_request rr
JOIN equipment_model em
    ON em.id = rr.equipment_model_id
JOIN equipment_type et
    ON et.id = em.equipment_type_id
JOIN issue_type it
    ON it.id = rr.issue_type_id
JOIN request_status rs
    ON rs.id = rr.status_id
JOIN app_user client_user
    ON client_user.id = rr.client_id
LEFT JOIN app_user master_user
    ON master_user.id = rr.master_id
LEFT JOIN (
    SELECT
        rsp.request_id,
        string_agg(sp.name, ', ' ORDER BY sp.name) AS parts_list
    FROM request_spare_part rsp
    JOIN spare_part sp ON sp.id = rsp.spare_part_id
    GROUP BY rsp.request_id
) parts ON parts.request_id = rr.id;

-- =========================================================
-- Отчет 2: Количество выполненных заявок по типам техники
-- =========================================================

CREATE OR REPLACE VIEW v_equipment_completed_stats AS
SELECT
    et.name      AS equipment_type,
    COUNT(*)     AS completed_count
FROM repair_request rr
JOIN equipment_model em
    ON em.id = rr.equipment_model_id
JOIN equipment_type et
    ON et.id = em.equipment_type_id
JOIN request_status rs
    ON rs.id = rr.status_id
WHERE rs.is_final = TRUE
GROUP BY et.name;

-- =========================================================
-- Отчет 3: Среднее время ремонта (в днях) по типам техники
-- =========================================================

CREATE OR REPLACE VIEW v_equipment_avg_repair_time AS
SELECT
    et.name AS equipment_type,
    ROUND(
        AVG((rr.completion_date - rr.start_date)::numeric),
        2
    ) AS avg_days
FROM repair_request rr
JOIN equipment_model em
    ON em.id = rr.equipment_model_id
JOIN equipment_type et
    ON et.id = em.equipment_type_id
JOIN request_status rs
    ON rs.id = rr.status_id
WHERE rs.is_final = TRUE
  AND rr.completion_date IS NOT NULL
  AND rr.completion_date >= rr.start_date
GROUP BY et.name;

-- =========================================================
-- Отчет 4: Топ типов неисправностей
-- =========================================================

CREATE OR REPLACE VIEW v_issue_type_stats AS
SELECT
    it.name AS issue_type,
    COUNT(*) AS cnt
FROM repair_request rr
JOIN issue_type it
    ON it.id = rr.issue_type_id
GROUP BY it.name;

-- =========================================================
-- Отчет 5: Нагрузка мастеров (активные заявки, не финальные)
-- =========================================================

CREATE OR REPLACE VIEW v_master_active_load AS
SELECT
    u.id     AS master_id,
    u.fio    AS master_fio,
    COUNT(*) AS active_requests
FROM repair_request rr
JOIN request_status rs
    ON rs.id = rr.status_id
JOIN app_user u
    ON u.id = rr.master_id
JOIN user_role ur
    ON ur.id = u.role_id
WHERE rs.is_final = FALSE
  AND ur.name IN ('Мастер', 'Специалист')
GROUP BY u.id, u.fio;

-- =========================================================
-- Отчет 6: Просроченные заявки (есть due_date, статус не финальный)
-- =========================================================

CREATE OR REPLACE VIEW v_overdue_requests AS
SELECT
    rr.id AS request_id,
    rr.start_date,
    rr.due_date,
    rs.name AS status,
    client_user.fio AS client_fio,
    client_user.phone AS client_phone,
    master_user.fio AS master_fio
FROM repair_request rr
JOIN request_status rs ON rs.id = rr.status_id
JOIN app_user client_user ON client_user.id = rr.client_id
LEFT JOIN app_user master_user ON master_user.id = rr.master_id
WHERE rr.due_date IS NOT NULL
  AND rs.is_final = FALSE
  AND rr.due_date < CURRENT_DATE;

-- =========================================================
-- Отчет 7: Открытые запросы помощи менеджеру по качеству (Задание 3)
-- =========================================================

CREATE OR REPLACE VIEW v_help_requests_open AS
SELECT
    hr.id AS help_id,
    hr.request_id AS request_id,
    hr.status AS status,
    hr.message AS message,
    hr.created_at AS created_at,
    req.status_id AS request_status_id,
    rs.name AS request_status,
    req.due_date AS due_date,
    client_user.fio AS client_fio,
    client_user.phone AS client_phone,
    master_user.fio AS current_master_fio,
    hr.created_by_master_id AS created_by_master_id,
    created_by.fio AS created_by_master_fio
FROM help_request hr
JOIN repair_request req ON req.id = hr.request_id
JOIN request_status rs ON rs.id = req.status_id
JOIN app_user client_user ON client_user.id = req.client_id
LEFT JOIN app_user master_user ON master_user.id = req.master_id
JOIN app_user created_by ON created_by.id = hr.created_by_master_id
WHERE hr.status = 'open';