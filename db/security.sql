DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_manager') THEN
        CREATE ROLE svc_manager NOLOGIN;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_operator') THEN
        CREATE ROLE svc_operator NOLOGIN;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_master') THEN
        CREATE ROLE svc_master NOLOGIN;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_client') THEN
        CREATE ROLE svc_client NOLOGIN;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_quality_manager') THEN
        CREATE ROLE svc_quality_manager NOLOGIN;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_specialist') THEN
        CREATE ROLE svc_specialist NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO
    svc_manager, svc_operator, svc_master, svc_client, svc_quality_manager, svc_specialist;

-- Менеджер: полный доступ
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO svc_manager;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO svc_manager;

-- Оператор: справочники + заявки/комментарии + запчасти + запросы помощи
GRANT SELECT ON user_role, request_status, equipment_type, equipment_model, issue_type TO svc_operator;
GRANT SELECT, INSERT, UPDATE, DELETE ON
    repair_request, request_comment,
    spare_part, request_spare_part,
    help_request
TO svc_operator;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO svc_operator;

-- Мастер: справочники + работа с заявками/комментариями + фиксация запчастей + создание запросов помощи
GRANT SELECT ON user_role, request_status, equipment_type, equipment_model, issue_type TO svc_master;
GRANT SELECT, UPDATE ON repair_request TO svc_master;
GRANT SELECT, INSERT ON request_comment TO svc_master;
GRANT SELECT, INSERT, UPDATE ON request_spare_part TO svc_master;
GRANT SELECT, INSERT ON spare_part TO svc_master;
GRANT SELECT, INSERT ON help_request TO svc_master;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO svc_master;

-- Заказчик: справочники + создание/редактирование заявок (ограничения — на уровне приложения)
GRANT SELECT ON request_status, equipment_type, equipment_model, issue_type TO svc_client;
GRANT SELECT, INSERT, UPDATE ON repair_request TO svc_client;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO svc_client;

-- Менеджер по качеству: доступ к заявкам + обработка запросов помощи + продление сроков
GRANT SELECT ON user_role, request_status, equipment_type, equipment_model, issue_type TO svc_quality_manager;
GRANT SELECT, INSERT, UPDATE ON
    repair_request, request_comment,
    spare_part, request_spare_part,
    help_request
TO svc_quality_manager;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO svc_quality_manager;

-- legacy specialist role
GRANT SELECT ON user_role, request_status, equipment_type, equipment_model, issue_type TO svc_specialist;
GRANT SELECT, UPDATE ON repair_request TO svc_specialist;
GRANT SELECT, INSERT ON request_comment TO svc_specialist;
GRANT SELECT, INSERT, UPDATE ON request_spare_part TO svc_specialist;
GRANT SELECT, INSERT ON spare_part TO svc_specialist;
GRANT SELECT, INSERT ON help_request TO svc_specialist;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO svc_specialist;