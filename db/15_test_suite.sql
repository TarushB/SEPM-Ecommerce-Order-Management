-- =====================================================================
-- 15_test_suite.sql  --  automated database test cases (TestPlan §6.1–6.3)
-- Every test runs inside BEGIN ... ROLLBACK, so the database is unchanged.
-- Run:  psql -U postgres -d olist -f db/15_test_suite.sql
-- Each test prints "TC-xx ..." followed by the result or the expected error.
-- =====================================================================
\set ON_ERROR_STOP 0
\pset footer off
\set VERBOSITY terse

\echo '===== TC-02  Row counts after load ====='
SELECT 'orders' t, COUNT(*) FROM orders UNION ALL
SELECT 'order_item', COUNT(*) FROM order_item UNION ALL
SELECT 'payment', COUNT(*) FROM payment UNION ALL
SELECT 'review', COUNT(*) FROM review UNION ALL
SELECT 'customer_account', COUNT(*) FROM customer_account UNION ALL
SELECT 'seller', COUNT(*) FROM seller UNION ALL
SELECT 'product', COUNT(*) FROM product UNION ALL
SELECT 'zip_code', COUNT(*) FROM zip_code UNION ALL
SELECT 'state', COUNT(*) FROM state;

\echo '===== TC-03  order_item with an unknown product_id (expect FK violation) ====='
BEGIN;
INSERT INTO order_item(order_id, order_item_id, product_id, seller_id, shipping_limit_date, price, freight_value)
SELECT order_id, 99, 'ffffffffffffffffffffffffffffffff', seller_id, now(), 10, 1 FROM order_item LIMIT 1;
ROLLBACK;

\echo '===== TC-04  payment with a negative value (expect CHECK violation) ====='
BEGIN;
INSERT INTO payment(order_id, payment_sequential, payment_type, installments, payment_value)
SELECT order_id, 99, 'credit_card', 1, -5 FROM orders LIMIT 1;
ROLLBACK;

\echo '===== TC-05  data-quality view (expect anomalies listed) ====='
SELECT * FROM v_data_quality;

\echo '===== TC-06  delivered -> shipped (expect error, status unchanged) ====='
BEGIN;
UPDATE orders SET order_status = 'shipped'
 WHERE order_id = (SELECT order_id FROM orders WHERE order_status = 'delivered' ORDER BY order_id LIMIT 1);
ROLLBACK;

\echo '===== TC-07 / TC-08  approved -> shipped allowed, audit row written ====='
BEGIN;
CREATE TEMP TABLE t_one AS SELECT order_id FROM orders WHERE order_status = 'approved' ORDER BY order_id LIMIT 1;
UPDATE orders SET order_status = 'shipped' WHERE order_id = (SELECT order_id FROM t_one);
SELECT order_id, order_status FROM orders WHERE order_id = (SELECT order_id FROM t_one);
SELECT order_id, old_status, new_status, changed_by FROM order_status_log
 WHERE order_id = (SELECT order_id FROM t_one) ORDER BY log_id DESC LIMIT 1;
ROLLBACK;

\echo '===== TC-09  delete a delivered order (expect error) ====='
BEGIN;
DELETE FROM orders WHERE order_id = (SELECT order_id FROM orders WHERE order_status = 'delivered' ORDER BY order_id LIMIT 1);
ROLLBACK;

\echo '===== TC-10  review for an order in processing (expect error) ====='
BEGIN;
INSERT INTO review(review_id, order_id, review_score, creation_date)
SELECT 'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee', order_id, 5, now() FROM orders WHERE order_status = 'processing' LIMIT 1;
ROLLBACK;

-- psql variables are used because CALL arguments cannot contain subqueries
SELECT customer_id AS cust FROM customer_account ORDER BY customer_id LIMIT 1 \gset
SELECT order_id AS delivered_id FROM orders WHERE order_status = 'delivered' ORDER BY order_id LIMIT 1 \gset
SELECT jsonb_agg(jsonb_build_object('product_id', product_id, 'seller_id', seller_id))::text AS two_items
  FROM (SELECT product_id, seller_id FROM order_item ORDER BY order_id, order_item_id LIMIT 2) s \gset
SELECT product_id AS p1, seller_id AS s1 FROM order_item ORDER BY order_id, order_item_id LIMIT 1 \gset

\echo '===== TC-11  sp_place_order with a valid customer and 2 items ====='
BEGIN;
CREATE TEMP TABLE t_items AS
  SELECT p.product_id, p.stock_qty AS stock_before FROM product p
   WHERE p.product_id IN (SELECT e->>'product_id' FROM jsonb_array_elements(:'two_items'::jsonb) e);
CALL sp_place_order(:'cust', :'two_items'::jsonb, 'credit_card', 1, NULL);
SELECT order_id AS new_id FROM orders WHERE customer_id = :'cust' ORDER BY purchase_ts DESC LIMIT 1 \gset
SELECT (SELECT COUNT(*) FROM orders     WHERE order_id = :'new_id') AS orders_rows,
       (SELECT COUNT(*) FROM order_item WHERE order_id = :'new_id') AS item_rows,
       (SELECT COUNT(*) FROM payment    WHERE order_id = :'new_id') AS payment_rows;
SELECT t.product_id, t.stock_before, p.stock_qty AS stock_after FROM t_items t JOIN product p USING (product_id);
ROLLBACK;

\echo '===== TC-12  sp_place_order with an unknown customer (expect error, nothing inserted) ====='
SELECT COUNT(*) AS orders_before FROM orders;
BEGIN;
CALL sp_place_order('00000000000000000000000000000000', :'two_items'::jsonb);
ROLLBACK;
SELECT COUNT(*) AS orders_after FROM orders;

\echo '===== TC-13  2 units of a product with stock 1 (expect CHECK stock_qty >= 0, whole order rolled back) ====='
BEGIN;
UPDATE product SET stock_qty = 1 WHERE product_id = :'p1';
SELECT COUNT(*) AS orders_before FROM orders \gset
SAVEPOINT before_call;
CALL sp_place_order(:'cust', jsonb_build_array(jsonb_build_object('product_id', :'p1', 'seller_id', :'s1'),
                                               jsonb_build_object('product_id', :'p1', 'seller_id', :'s1')));
ROLLBACK TO SAVEPOINT before_call;
SELECT stock_qty AS stock_after_failed_order,
       (SELECT COUNT(*) FROM orders) - :orders_before AS orders_added
  FROM product WHERE product_id = :'p1';
ROLLBACK;

\echo '===== TC-14  sp_cancel_order on a delivered order (expect error) ====='
BEGIN;
CALL sp_cancel_order(:'delivered_id');
ROLLBACK;

\echo '===== TC-15  fn_login with a wrong password (expect no row) ====='
SELECT * FROM fn_login('admin', 'wrong-password');
\echo '      ... and with the right password'
SELECT * FROM fn_login('admin', 'admin123');

\echo '===== TC-16  read password_hash as olist_app (expect permission denied) ====='
BEGIN;
SET LOCAL ROLE olist_app;
SELECT password_hash FROM app_user LIMIT 1;
ROLLBACK;

\echo '===== TC-17  seller sees only its own orders (RLS) ====='
BEGIN;
SELECT set_config('app.seller_id', (SELECT seller_id FROM app_user WHERE username = 'seller'), true);
SELECT COUNT(*) AS orders_total_as_admin FROM orders;
SET LOCAL ROLE olist_seller;
SELECT COUNT(*) AS orders_visible_to_seller FROM orders;
SELECT COUNT(*) AS foreign_orders_visible FROM orders o
 WHERE NOT EXISTS (SELECT 1 FROM order_item oi WHERE oi.order_id = o.order_id
                     AND oi.seller_id = current_setting('app.seller_id'));
ROLLBACK;

\echo '===== TC-18  analyst selects zip_code.lat (expect permission denied) ====='
BEGIN;
SET LOCAL ROLE olist_analyst;
SELECT zip_prefix, city FROM zip_code LIMIT 1;
SELECT lat FROM zip_code LIMIT 1;
ROLLBACK;

\echo '===== TC-19  analyst deletes a product (expect permission denied, SQLSTATE 42501) ====='
BEGIN;
SET LOCAL ROLE olist_analyst;
\set VERBOSITY verbose
DELETE FROM product WHERE product_id = (SELECT product_id FROM product LIMIT 1);
\set VERBOSITY terse
ROLLBACK;

\echo '===== TC-21  DELETE inside a read-only transaction (expect rejected) ====='
BEGIN;
SET TRANSACTION READ ONLY;
DELETE FROM orders;
ROLLBACK;

\echo '===== END OF SUITE ====='
