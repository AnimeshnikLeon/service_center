-- Проверки целостности и "диагностические" запросы по 3НФ.
-- Это не формальное доказательство 3НФ (оно делается анализом зависимостей),
-- но набор полезных проверок, подтверждающих нормализацию и ссылочную целостность.

-- 1) Проверка уникальностей (справочники)
SELECT 'user_role duplicates' AS check_name, name, COUNT(*) AS cnt
FROM user_role
GROUP BY name
HAVING COUNT(*) > 1;

SELECT 'request_status duplicates' AS check_name, name, COUNT(*) AS cnt
FROM request_status
GROUP BY name
HAVING COUNT(*) > 1;

SELECT 'equipment_type duplicates' AS check_name, name, COUNT(*) AS cnt
FROM equipment_type
GROUP BY name
HAVING COUNT(*) > 1;

SELECT 'equipment_model duplicates by type' AS check_name, equipment_type_id, name, COUNT(*) AS cnt
FROM equipment_model
GROUP BY equipment_type_id, name
HAVING COUNT(*) > 1;

SELECT 'issue_type duplicates' AS check_name, name, COUNT(*) AS cnt
FROM issue_type
GROUP BY name
HAVING COUNT(*) > 1;

SELECT 'spare_part duplicates' AS check_name, name, COUNT(*) AS cnt
FROM spare_part
GROUP BY name
HAVING COUNT(*) > 1;

-- 2) Проверка ссылочной целостности (ручная диагностика, если вдруг нарушили FK в обходе)
SELECT 'repair_request missing equipment_model' AS check_name, rr.id
FROM repair_request rr
LEFT JOIN equipment_model em ON em.id = rr.equipment_model_id
WHERE em.id IS NULL;

SELECT 'repair_request missing issue_type' AS check_name, rr.id
FROM repair_request rr
LEFT JOIN issue_type it ON it.id = rr.issue_type_id
WHERE it.id IS NULL;

SELECT 'repair_request missing status' AS check_name, rr.id
FROM repair_request rr
LEFT JOIN request_status rs ON rs.id = rr.status_id
WHERE rs.id IS NULL;

SELECT 'repair_request missing client' AS check_name, rr.id
FROM repair_request rr
LEFT JOIN app_user u ON u.id = rr.client_id
WHERE u.id IS NULL;

SELECT 'request_comment missing request' AS check_name, rc.id
FROM request_comment rc
LEFT JOIN repair_request rr ON rr.id = rc.request_id
WHERE rr.id IS NULL;

SELECT 'request_spare_part missing request' AS check_name, rsp.id
FROM request_spare_part rsp
LEFT JOIN repair_request rr ON rr.id = rsp.request_id
WHERE rr.id IS NULL;

SELECT 'request_spare_part missing spare_part' AS check_name, rsp.id
FROM request_spare_part rsp
LEFT JOIN spare_part sp ON sp.id = rsp.spare_part_id
WHERE sp.id IS NULL;

-- 3) Проверка нормализации запчастей (нет дубликатов "та же запчасть в той же заявке")
SELECT 'duplicate part in same request' AS check_name, request_id, spare_part_id, COUNT(*) AS cnt
FROM request_spare_part
GROUP BY request_id, spare_part_id
HAVING COUNT(*) > 1;

-- 4) Проверка бизнес-ограничений по датам
SELECT 'completion_date before start_date' AS check_name, id, start_date, completion_date
FROM repair_request
WHERE completion_date IS NOT NULL AND completion_date < start_date;

SELECT 'due_date before start_date' AS check_name, id, start_date, due_date
FROM repair_request
WHERE due_date IS NOT NULL AND due_date < start_date;

-- 5) "Доказательная" проверка факта вынесения повторяющихся групп:
--    раньше запчасти были "repair_parts" в repair_request,
--    теперь есть справочник spare_part и связь request_spare_part.
--    Этот запрос показывает заявки, где legacy поле заполнено, а нормализованные записи отсутствуют.
SELECT
    rr.id AS request_id,
    rr.repair_parts AS repair_parts_legacy
FROM repair_request rr
LEFT JOIN request_spare_part rsp ON rsp.request_id = rr.id
WHERE COALESCE(NULLIF(BTRIM(rr.repair_parts), ''), '') <> ''
  AND rsp.id IS NULL;