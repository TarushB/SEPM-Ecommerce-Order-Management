-- =====================================================================
-- 07_procedures.sql  --  stored procedures (CALL) and functions (SELECT)
-- =====================================================================
SET client_min_messages = warning;

-- ---------------------------------------------------------------------
-- sp_place_order: creates an order, its items and its payment as ONE
-- atomic unit. If any item is invalid (unknown product, out of stock,
-- bad price) the whole order is rolled back - nothing is left behind.
--   p_items = '[{"product_id":"...","seller_id":"...","price":99.9,"freight":12.5}, ...]'
--   price / freight are optional: defaults = the product's last sold price
--   and its average freight.
-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE sp_place_order(
    p_customer_id  CHAR(32),
    p_items        JSONB,
    p_payment_type VARCHAR DEFAULT 'credit_card',
    p_installments INT     DEFAULT 1,
    INOUT p_order_id CHAR(32) DEFAULT NULL)
LANGUAGE plpgsql AS $$
DECLARE
    v_item    JSONB;
    v_seq     INT := 0;
    v_price   NUMERIC(10,2);
    v_freight NUMERIC(10,2);
    v_total   NUMERIC(12,2) := 0;
    v_days    NUMERIC;
BEGIN
    IF p_items IS NULL OR jsonb_array_length(p_items) = 0 THEN
        RAISE EXCEPTION 'An order needs at least one item';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM customer_account WHERE customer_id = p_customer_id) THEN
        RAISE EXCEPTION 'Unknown customer %', p_customer_id USING ERRCODE = 'foreign_key_violation';
    END IF;

    p_order_id := md5(random()::text || clock_timestamp()::text);

    -- promised delivery = historical average promise for the customer's state
    SELECT COALESCE(ROUND(AVG(EXTRACT(EPOCH FROM o.estimated_delivery_date - o.purchase_ts) / 86400)), 24)
      INTO v_days
      FROM orders o
      JOIN customer_account ca ON ca.customer_id = o.customer_id
      JOIN zip_code z          ON z.zip_prefix   = ca.zip_prefix
     WHERE z.state_code = (SELECT z2.state_code FROM customer_account c2
                           JOIN zip_code z2 ON z2.zip_prefix = c2.zip_prefix
                           WHERE c2.customer_id = p_customer_id);

    INSERT INTO orders(order_id, customer_id, order_status, purchase_ts, estimated_delivery_date)
    VALUES (p_order_id, p_customer_id, 'created', now()::timestamp(0),
            (now() + make_interval(days => v_days::int))::timestamp(0));

    FOR v_item IN SELECT * FROM jsonb_array_elements(p_items) LOOP
        v_seq := v_seq + 1;
        v_price := NULLIF(v_item->>'price', '')::numeric;
        IF v_price IS NULL THEN
            SELECT price INTO v_price FROM order_item
             WHERE product_id = v_item->>'product_id'
             ORDER BY shipping_limit_date DESC NULLS LAST LIMIT 1;
        END IF;
        v_freight := NULLIF(v_item->>'freight', '')::numeric;
        IF v_freight IS NULL THEN
            SELECT ROUND(AVG(freight_value), 2) INTO v_freight FROM order_item
             WHERE product_id = v_item->>'product_id';
        END IF;

        -- FK, CHECK (price > 0) and the stock trigger enforce the rules here
        INSERT INTO order_item(order_id, order_item_id, product_id, seller_id,
                               shipping_limit_date, price, freight_value)
        VALUES (p_order_id, v_seq, v_item->>'product_id', v_item->>'seller_id',
                (now() + interval '6 days')::timestamp(0), v_price, COALESCE(v_freight, 0));
        v_total := v_total + v_price + COALESCE(v_freight, 0);
    END LOOP;

    INSERT INTO payment(order_id, payment_sequential, payment_type, installments, payment_value)
    VALUES (p_order_id, 1, p_payment_type, GREATEST(p_installments, 1), v_total);
END $$;

-- ---------------------------------------------------------------------
-- sp_update_status: moves an order forward and stamps the matching date.
-- The transition rule itself lives in trigger trg_validate_status_transition.
-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE sp_update_status(p_order_id CHAR(32), p_new_status VARCHAR)
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE orders
       SET order_status            = p_new_status,
           approved_at             = CASE WHEN p_new_status = 'approved'  THEN now()::timestamp(0) ELSE approved_at END,
           delivered_carrier_date  = CASE WHEN p_new_status = 'shipped'   THEN now()::timestamp(0) ELSE delivered_carrier_date END,
           delivered_customer_date = CASE WHEN p_new_status = 'delivered' THEN now()::timestamp(0) ELSE delivered_customer_date END
     WHERE order_id = p_order_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Order % not found', p_order_id USING ERRCODE = 'no_data_found';
    END IF;
END $$;

-- ---------------------------------------------------------------------
-- sp_cancel_order: cancel + give the stock back, in one transaction.
-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE sp_cancel_order(p_order_id CHAR(32))
LANGUAGE plpgsql AS $$
DECLARE v_status TEXT;
BEGIN
    SELECT order_status INTO v_status FROM orders WHERE order_id = p_order_id FOR UPDATE;
    IF v_status IS NULL THEN
        RAISE EXCEPTION 'Order % not found', p_order_id USING ERRCODE = 'no_data_found';
    END IF;
    IF v_status IN ('shipped','delivered') THEN
        RAISE EXCEPTION 'Order % is already %, it cannot be canceled', p_order_id, v_status
              USING ERRCODE = 'check_violation';
    END IF;
    UPDATE orders SET order_status = 'canceled' WHERE order_id = p_order_id;
    UPDATE product p SET stock_qty = p.stock_qty + x.n
      FROM (SELECT product_id, COUNT(*) AS n FROM order_item
             WHERE order_id = p_order_id GROUP BY product_id) x
     WHERE p.product_id = x.product_id;
END $$;

-- ---------------------------------------------------------------------
-- Scalar functions used in queries and screens
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_order_total(p_order_id CHAR(32)) RETURNS NUMERIC
LANGUAGE sql STABLE AS $$
    SELECT COALESCE(SUM(price + freight_value), 0) FROM order_item WHERE order_id = p_order_id
$$;

CREATE OR REPLACE FUNCTION fn_seller_rating(p_seller_id CHAR(32)) RETURNS NUMERIC
LANGUAGE sql STABLE AS $$
    SELECT ROUND(AVG(r.review_score), 2)
    FROM review r
    WHERE r.order_id IN (SELECT order_id FROM order_item WHERE seller_id = p_seller_id)
$$;

CREATE OR REPLACE FUNCTION fn_delivery_days(p_order_id CHAR(32)) RETURNS NUMERIC
LANGUAGE sql STABLE AS $$
    SELECT ROUND(EXTRACT(EPOCH FROM delivered_customer_date - purchase_ts) / 86400, 1)
    FROM orders WHERE order_id = p_order_id
$$;

-- Refresh the materialized views (run after bulk changes / before training)
CREATE OR REPLACE PROCEDURE sp_refresh_reports()
LANGUAGE plpgsql AS $$
BEGIN
    REFRESH MATERIALIZED VIEW mv_seller_delivery_history;
    REFRESH MATERIALIZED VIEW mv_order_features;
END $$;

-- ---------------------------------------------------------------------
-- fn_login: checks a password against the bcrypt hash INSIDE the database.
-- SECURITY DEFINER lets the low-privilege app role call it without being
-- able to read app_user (so password hashes never leave the DB).
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_login(p_username TEXT, p_password TEXT)
RETURNS TABLE(user_id INT, username VARCHAR, app_role VARCHAR, seller_id CHAR(32))
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT u.user_id, u.username, u.app_role, u.seller_id
    FROM app_user u
    WHERE u.username = p_username
      AND u.is_active
      AND u.password_hash = crypt(p_password, u.password_hash)
$$;

CREATE OR REPLACE PROCEDURE sp_create_user(p_username TEXT, p_password TEXT,
                                           p_role TEXT, p_seller_id CHAR(32) DEFAULT NULL)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    INSERT INTO app_user(username, password_hash, app_role, seller_id)
    VALUES (p_username, crypt(p_password, gen_salt('bf', 8)), p_role, p_seller_id)
    ON CONFLICT (username) DO UPDATE
       SET password_hash = EXCLUDED.password_hash, app_role = EXCLUDED.app_role,
           seller_id = EXCLUDED.seller_id, is_active = true;
$$;
