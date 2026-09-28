-- =====================================================================
-- 10_transactions_demo.sql  --  ACID demonstrations (single session)
-- Run:  psql -U postgres -d olist -f 10_transactions_demo.sql
-- Every demo cleans up after itself (ROLLBACK), so it can be re-run.
-- =====================================================================
\set ON_ERROR_STOP 0
\set demo_customer '''9ef432eb6251297304e76186b10a928d'''
\set demo_product  '''4244733e06e7ecb4970a6e2683c13e61'''
\set demo_seller   '''48436dade18ac8b2bce089ec2a041202'''

\echo
\echo ===== A. ATOMICITY: all-or-nothing =====
\echo Order with a valid first item and an unknown product as the second item.
SELECT COUNT(*) AS orders_before FROM orders;
CALL sp_place_order(:demo_customer,
     jsonb_build_array(
        jsonb_build_object('product_id', :demo_product, 'seller_id', :demo_seller, 'price', 50, 'freight', 10),
        jsonb_build_object('product_id', 'this_product_does_not_exist_0000', 'seller_id', :demo_seller, 'price', 20, 'freight', 5)));
\echo The FK error above aborted the whole CALL: no order, no first item, no payment remain.
SELECT COUNT(*) AS orders_after FROM orders;

\echo
\echo ----- A2. SAVEPOINT: undo part of a transaction, keep the rest -----
BEGIN;
UPDATE product SET stock_qty = stock_qty + 10 WHERE product_id = :demo_product;
SAVEPOINT before_price_change;
UPDATE order_item SET price = -1 WHERE order_id = 'e481f51cbdc54678b7cc49136f2d6af7';   -- fails CHECK
ROLLBACK TO SAVEPOINT before_price_change;
SELECT stock_qty AS stock_after_partial_rollback FROM product WHERE product_id = :demo_product;
ROLLBACK;   -- undo the demo completely

\echo
\echo ===== B. CONSISTENCY: constraints reject invalid states =====
INSERT INTO review(review_id, order_id, review_score, creation_date)
VALUES ('demo_review_0000000000000000000', 'e481f51cbdc54678b7cc49136f2d6af7', 7, now());      -- CHECK score 1..5
INSERT INTO order_item(order_id, order_item_id, product_id, seller_id, price, freight_value)
VALUES ('e481f51cbdc54678b7cc49136f2d6af7', 99, :demo_product, :demo_seller, -5, 0);            -- CHECK price > 0
INSERT INTO orders(order_id, customer_id, order_status, purchase_ts, estimated_delivery_date)
VALUES ('demo_order_00000000000000000000', 'no_such_customer_000000000000000', 'created', now(), now());  -- FK
UPDATE orders SET order_status = 'processing' WHERE order_id = 'e481f51cbdc54678b7cc49136f2d6af7';   -- trigger: delivered is final
UPDATE product SET stock_qty = -1 WHERE product_id = :demo_product;                              -- CHECK stock >= 0

\echo
\echo ===== C. ISOLATION: see 11_concurrency_demo.sql (needs two sessions) =====

\echo
\echo ===== D. DURABILITY =====
\echo 1) Run:  CALL sp_place_order(...) in autocommit mode and note the order_id.
\echo 2) Restart PostgreSQL (Windows: services.msc -> postgresql-x64-16 -> Restart).
\echo 3) SELECT * FROM orders WHERE order_id = '<that id>';  -> the row is still there,
\echo    because COMMIT returns only after the change is written to the write-ahead log (WAL).
SHOW synchronous_commit;
SHOW wal_level;

\echo
\echo ===== E. A full successful transaction, then rolled back for re-runs =====
BEGIN;
CALL sp_place_order(:demo_customer,
     jsonb_build_array(jsonb_build_object('product_id', :demo_product, 'seller_id', :demo_seller)),
     'boleto', 1, NULL);
SELECT o.order_id, o.order_status, fn_order_total(o.order_id) AS total,
       (SELECT payment_value FROM payment p WHERE p.order_id = o.order_id) AS paid,
       (SELECT COUNT(*) FROM order_status_log l WHERE l.order_id = o.order_id) AS audit_rows
FROM orders o WHERE o.purchase_ts >= now()::timestamp(0) - interval '1 minute';
SELECT order_id AS new_order FROM orders ORDER BY purchase_ts DESC LIMIT 1 \gset
CALL sp_update_status(:'new_order', 'approved');
SELECT order_id, old_status, new_status, changed_by FROM order_status_log ORDER BY log_id DESC LIMIT 2;
ROLLBACK;
