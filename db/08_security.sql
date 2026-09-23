-- =====================================================================
-- 08_security.sql  --  role-based access control
--   * 5 group roles (NOLOGIN) = the 5 application roles
--   * 1 login role  olist_app  used by the web app. It is NOINHERIT, so it
--     has no data privileges of its own: for every request the app runs
--     SET ROLE <user's role>, and PostgreSQL enforces that role's rights.
--   * Row-level security: a seller sees only orders containing their items.
--   * Column-level privilege: analysts can't read exact coordinates.
--   * Demo users stored with bcrypt hashes (pgcrypto).
-- =====================================================================
SET client_min_messages = warning;

-- 1. Roles (roles are cluster-wide, so create them only if missing) -------
DO $$
DECLARE r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['olist_admin','olist_manager','olist_analyst','olist_seller','olist_support'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN', r);
        END IF;
    END LOOP;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'olist_app') THEN
        CREATE ROLE olist_app LOGIN NOINHERIT PASSWORD 'olist_app_pw';
    END IF;
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO olist_app', current_database());
END $$;

GRANT olist_admin, olist_manager, olist_analyst, olist_seller, olist_support TO olist_app;

-- 2. Start from zero -------------------------------------------------------
REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL PROCEDURES IN SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO olist_admin, olist_manager, olist_analyst, olist_seller, olist_support, olist_app;

-- 3. admin: everything ------------------------------------------------------
GRANT ALL ON ALL TABLES     IN SCHEMA public TO olist_admin;
GRANT ALL ON ALL SEQUENCES  IN SCHEMA public TO olist_admin;
GRANT EXECUTE ON ALL FUNCTIONS  IN SCHEMA public TO olist_admin;
GRANT EXECUTE ON ALL PROCEDURES IN SCHEMA public TO olist_admin;
GRANT CREATE ON SCHEMA public TO olist_admin;

-- 4. manager: full CRUD on business data, all reports, no user management ---
GRANT SELECT, INSERT, UPDATE, DELETE ON
      state, zip_code, customer, customer_account, seller, category, product,
      orders, order_item, payment_type, payment, review, ml_prediction
      TO olist_manager;
GRANT SELECT ON order_status_log, ml_model, mv_order_features, mv_seller_delivery_history,
      v_order_features, v_order_details, v_seller_performance, v_monthly_sales,
      v_customer_public, v_data_quality, v_high_risk_orders TO olist_manager;
GRANT SELECT, INSERT, UPDATE ON v_sp_customers TO olist_manager;
GRANT EXECUTE ON PROCEDURE sp_place_order, sp_update_status, sp_cancel_order, sp_refresh_reports
      TO olist_manager;
GRANT EXECUTE ON FUNCTION fn_order_total, fn_seller_rating, fn_delivery_days, fn_status_rank
      TO olist_manager, olist_analyst, olist_support, olist_seller;

-- 5. analyst: read-only; exact coordinates hidden via column privileges ----
GRANT SELECT ON state, customer, customer_account, seller, category, product,
      orders, order_item, payment_type, payment, review, order_status_log,
      ml_model, ml_prediction, mv_order_features, v_order_features, v_order_details,
      v_seller_performance, v_monthly_sales, v_customer_public, v_data_quality,
      v_high_risk_orders TO olist_analyst;
GRANT SELECT (zip_prefix, city, state_code) ON zip_code TO olist_analyst;   -- no lat/lng

-- 6. support: customer service - read orders, answer reviews, no deletes ---
GRANT SELECT ON v_customer_public, v_order_details, orders, order_item, product,
      category, payment, payment_type, review, order_status_log, state TO olist_support;
GRANT SELECT (zip_prefix, city, state_code) ON zip_code TO olist_support;
GRANT UPDATE (answer_ts) ON review TO olist_support;
