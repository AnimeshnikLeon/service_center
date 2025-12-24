-- Протокол функционального тестирования SQL-отчетов (Задание 2).
-- Сценарий: выполнить запросы и убедиться, что данные корректно возвращаются.

-- Тест 1: полный список заявок (последние 20)
SELECT *
FROM v_request_full
ORDER BY request_id DESC
LIMIT 20;

-- Тест 2: выполненные заявки по типам техники
SELECT *
FROM v_equipment_completed_stats
ORDER BY completed_count DESC, equipment_type;

-- Тест 3: среднее время ремонта по типам техники
SELECT *
FROM v_equipment_avg_repair_time
ORDER BY avg_days DESC NULLS LAST, equipment_type;

-- Тест 4: топ типов неисправностей
SELECT *
FROM v_issue_type_stats
ORDER BY cnt DESC, issue_type;

-- Тест 5: нагрузка мастеров (активные)
SELECT *
FROM v_master_active_load
ORDER BY active_requests DESC, master_fio;

-- Тест 6: просроченные заявки
SELECT *
FROM v_overdue_requests
ORDER BY due_date ASC, request_id;

-- Тест 7: открытые запросы помощи (если есть)
SELECT *
FROM v_help_requests_open
ORDER BY created_at DESC, help_id;