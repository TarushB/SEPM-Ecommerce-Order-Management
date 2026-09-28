-- =====================================================================
-- 13_index_demo.sql  --  EXPLAIN ANALYZE with and without an index.
-- Drops each index inside a transaction, measures, then rolls back.
-- =====================================================================

\echo ===== 1. Seller's order lines: B-tree index on order_item(seller_id) =====
BEGIN;
DROP INDEX ix_order_item_seller;
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON)
SELECT * FROM order_item WHERE seller_id = '6560211a19b47992c3666cc44a7e94c0';
ROLLBACK;
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON)
SELECT * FROM order_item WHERE seller_id = '6560211a19b47992c3666cc44a7e94c0';

\echo ===== 2. Date-range report: index on orders(purchase_ts) =====
BEGIN;
DROP INDEX ix_orders_purchase_ts;
DROP INDEX ix_orders_status_ts;
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON)
SELECT COUNT(*) FROM orders WHERE purchase_ts BETWEEN '2018-01-01' AND '2018-01-07';
ROLLBACK;
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON)
SELECT COUNT(*) FROM orders WHERE purchase_ts BETWEEN '2018-01-01' AND '2018-01-07';

\echo ===== 3. Partial index: open orders only =====
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON)
SELECT order_id, purchase_ts FROM orders
WHERE order_status NOT IN ('delivered','canceled','unavailable') ORDER BY purchase_ts DESC LIMIT 20;

\echo ===== 4. Full-text search: GIN index vs sequential scan =====
BEGIN;
DROP INDEX ix_review_fts;
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON)
SELECT review_id FROM review
WHERE to_tsvector('portuguese', coalesce(comment_title,'') || ' ' || coalesce(comment_message,''))
      @@ plainto_tsquery('portuguese', 'atraso');
ROLLBACK;
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON)
SELECT review_id FROM review
WHERE to_tsvector('portuguese', coalesce(comment_title,'') || ' ' || coalesce(comment_message,''))
      @@ plainto_tsquery('portuguese', 'atraso');

\echo ===== 5. Index sizes (the cost side) =====
SELECT indexrelname AS index_name, relname AS table_name,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_stat_user_indexes ORDER BY pg_relation_size(indexrelid) DESC LIMIT 15;
