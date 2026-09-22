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
