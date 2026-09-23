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

-- 7. seller: only their own orders (row-level security below) --------------
GRANT SELECT ON orders, order_item, product, category, review, payment_type TO olist_seller;
GRANT SELECT (zip_prefix, city, state_code) ON zip_code TO olist_seller;
GRANT SELECT ON seller, state, v_customer_public TO olist_seller;
GRANT UPDATE (order_status, approved_at, delivered_carrier_date, delivered_customer_date)
      ON orders TO olist_seller;
GRANT EXECUTE ON PROCEDURE sp_update_status TO olist_seller;

-- 8. Row-level security ------------------------------------------------------
--    The app sets the seller's id with:  SELECT set_config('app.seller_id', '<id>', false)
ALTER TABLE orders     ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_item ENABLE ROW LEVEL SECURITY;
ALTER TABLE review     ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS p_staff  ON orders;
DROP POLICY IF EXISTS p_seller ON orders;
DROP POLICY IF EXISTS p_staff  ON order_item;
DROP POLICY IF EXISTS p_seller ON order_item;
DROP POLICY IF EXISTS p_staff  ON review;
DROP POLICY IF EXISTS p_seller ON review;

CREATE POLICY p_staff ON orders
    TO olist_admin, olist_manager, olist_analyst, olist_support USING (true) WITH CHECK (true);
CREATE POLICY p_seller ON orders TO olist_seller
    USING (EXISTS (SELECT 1 FROM order_item oi
                   WHERE oi.order_id = orders.order_id
                     AND oi.seller_id = current_setting('app.seller_id', true)));

CREATE POLICY p_staff ON order_item
    TO olist_admin, olist_manager, olist_analyst, olist_support USING (true) WITH CHECK (true);
CREATE POLICY p_seller ON order_item TO olist_seller
    USING (seller_id = current_setting('app.seller_id', true));

CREATE POLICY p_staff ON review
    TO olist_admin, olist_manager, olist_analyst, olist_support USING (true) WITH CHECK (true);
CREATE POLICY p_seller ON review TO olist_seller
    USING (EXISTS (SELECT 1 FROM order_item oi
                   WHERE oi.order_id = review.order_id
                     AND oi.seller_id = current_setting('app.seller_id', true)));

-- 9. Trigger functions that write to system tables run as their owner, so
--    a seller changing a status can still write the audit row.
ALTER FUNCTION trg_order_status_log()      SECURITY DEFINER;
ALTER FUNCTION trg_invalidate_prediction() SECURITY DEFINER;
ALTER FUNCTION trg_reduce_stock()          SECURITY DEFINER;
ALTER PROCEDURE sp_refresh_reports()       SECURITY DEFINER;

-- 10. Login is only possible through fn_login (password check in the DB) ---
GRANT EXECUTE ON FUNCTION fn_login(TEXT, TEXT) TO olist_app;

-- 11. Demo application users (password = username + '123') ---------------
CALL sp_create_user('admin',   'admin123',   'admin');
CALL sp_create_user('manager', 'manager123', 'manager');
CALL sp_create_user('analyst', 'analyst123', 'analyst');
CALL sp_create_user('support', 'support123', 'support');
DO $$
DECLARE v_seller CHAR(32);
BEGIN
    -- the seller with the most orders becomes the demo seller account
    SELECT seller_id INTO v_seller FROM order_item
    GROUP BY seller_id ORDER BY COUNT(DISTINCT order_id) DESC LIMIT 1;
    CALL sp_create_user('seller', 'seller123', 'seller', v_seller);
END $$;

SELECT username, app_role, seller_id, left(password_hash, 7) || '...' AS hash_prefix FROM app_user ORDER BY user_id;
